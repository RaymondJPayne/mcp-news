"""HTTP fetching with per-host politeness.

Two things matter here and nothing else does. First, we identify ourselves and
space out requests to the same host, because a self-hosted reader who gets
blocked has no support desk to appeal to. Second, conditional requests: a feed
polled every twenty minutes should transfer nothing at all most of the time.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx


@dataclass
class Response:
    status: int
    text: str
    content: bytes
    headers: dict[str, str]
    url: str
    not_modified: bool = False


class FetchError(Exception):
    """Anything that stopped us getting the bytes. Carries a catalogue key."""

    def __init__(self, message_key: str, detail: str = ""):
        super().__init__(detail or message_key)
        self.message_key = message_key
        self.detail = detail


@dataclass
class Fetcher:
    user_agent: str = "mcp-news/0.1"
    concurrency: int = 8
    per_host_delay_s: float = 2.0
    timeout_s: float = 30.0
    respect_robots: bool = True
    max_bytes: int = 2_000_000

    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _sem: asyncio.Semaphore | None = field(default=None, init=False, repr=False)
    _host_locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False, repr=False)
    _host_last: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _robots: dict[str, RobotFileParser | None] = field(
        default_factory=dict, init=False, repr=False)

    async def __aenter__(self) -> "Fetcher":
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(self.timeout_s),
            headers={"User-Agent": self.user_agent,
                     "Accept-Encoding": "gzip, deflate",
                     "Accept": "*/*"},
        )
        self._sem = asyncio.Semaphore(max(1, self.concurrency))
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---- politeness ------------------------------------------------------
    async def _wait_turn(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._host_last.get(host, 0.0)
            if elapsed < self.per_host_delay_s:
                await asyncio.sleep(self.per_host_delay_s - elapsed)
            self._host_last[host] = time.monotonic()

    async def allowed(self, url: str) -> bool:
        """robots.txt, cached per host. Failing to fetch it is treated as allowed."""
        if not self.respect_robots:
            return True
        host = urlsplit(url).netloc
        if host not in self._robots:
            parser: RobotFileParser | None = None
            try:
                assert self._client is not None
                scheme = urlsplit(url).scheme or "https"
                r = await self._client.get(f"{scheme}://{host}/robots.txt", timeout=10.0)
                if r.status_code == 200 and len(r.text) < 512_000:
                    parser = RobotFileParser()
                    parser.parse(r.text.splitlines())
            except (httpx.HTTPError, AssertionError):
                parser = None
            self._robots[host] = parser
        parser = self._robots[host]
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    # ---- the one method that does the work -------------------------------
    async def get(self, url: str, *, etag: str | None = None,
                  last_modified: str | None = None, check_robots: bool = False) -> Response:
        if self._client is None or self._sem is None:
            raise FetchError("err.generic", "fetcher used outside its context manager")
        host = urlsplit(url).netloc
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        async with self._sem:
            if check_robots and not await self.allowed(url):
                raise FetchError("err.source.unreachable", "disallowed by robots.txt")
            await self._wait_turn(host)
            try:
                r = await self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                raise FetchError("err.source.unreachable", str(exc)) from exc

        if r.status_code == 304:
            return Response(304, "", b"", dict(r.headers), str(r.url), not_modified=True)
        if r.status_code >= 400:
            raise FetchError("err.source.unreachable", f"HTTP {r.status_code}")
        content = r.content[:self.max_bytes]
        try:
            text = content.decode(r.encoding or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = content.decode("utf-8", errors="replace")
        return Response(r.status_code, text, content, dict(r.headers), str(r.url))
