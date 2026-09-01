"""The application context: one object that owns everything long-lived.

The API, the MCP server, the CLI and the background loops all read the same
store, the same profile and the same provider registry. Keeping that in one
place means "reload the profile" is one call rather than four, and a setting
changed in the dashboard takes effect without a restart.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from mcpnews import __version__, paths
from mcpnews.archive import Archive
from mcpnews.config import profile as profile_cfg
from mcpnews.config import providers as providers_cfg
from mcpnews.config import settings as settings_cfg
from mcpnews.config.profile import Profile
from mcpnews.config.settings import Settings
from mcpnews.providers.registry import ProviderRegistry
from mcpnews.rank.scorer import CompiledProfile
from mcpnews.sources import loader
from mcpnews.storage.registry import open_storage
from mcpnews.store.base import ArticleStore
from mcpnews.store.registry import open_store

log = logging.getLogger("mcpnews")


@dataclass
class App:
    settings: Settings
    store: ArticleStore
    archive: Archive
    providers: ProviderRegistry
    profile: Profile
    scorer: CompiledProfile

    # ---- construction ----------------------------------------------------
    @classmethod
    def create(cls) -> App:
        settings = settings_cfg.load()
        store = open_store(settings)
        archive = Archive(open_storage(settings))
        providers = ProviderRegistry()
        profile = profile_cfg.load() if profile_cfg.exists() else Profile()
        app = cls(settings=settings, store=store, archive=archive, providers=providers,
                  profile=profile, scorer=CompiledProfile(profile))
        if settings.configured:
            app.register_sources()
        return app

    def close(self) -> None:
        # Closing a store that is already closed, or was never opened, is not an
        # error worth propagating out of a shutdown path.
        with contextlib.suppress(Exception):
            self.store.close()

    # ---- reloading -------------------------------------------------------
    def reload_settings(self) -> None:
        self.settings = settings_cfg.load()

    def reload_profile(self) -> None:
        self.profile = profile_cfg.load() if profile_cfg.exists() else Profile()
        self.scorer = CompiledProfile(self.profile)

    def reload_providers(self) -> None:
        self.providers = ProviderRegistry()

    def register_sources(self) -> dict[str, int]:
        try:
            return loader.register_bundles(self.store, self.settings.bundles)
        except loader.BundleError as exc:
            log.error("source bundle error: %s", exc)
            return {"added": 0, "updated": 0}

    # ---- reporting -------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self.settings.configured

    def tier(self) -> int:
        return self.providers.tier()

    def status(self) -> dict:
        counts = self.store.counts()
        archive_desc = self.archive.storage.describe()
        return {
            "version": __version__,
            "tier": self.tier(),
            "configured": self.configured,
            "language": self.settings.language,
            "articles": counts["articles"],
            "enriched": counts["enriched"],
            "queued": counts["queued"],
            "clusters": counts.get("clusters", 0),
            "sources_active": counts["sources_active"],
            "sources_failing": counts["sources_failing"],
            "providers": self.providers.health(),
            "vector_spaces": [{"model_id": m, "count": n}
                              for m, n in self.store.vector_spaces()],
            "last_collection": self.store.get_meta("last_collection"),
            "database": str(self.settings.db_path),
            "archive": archive_desc,
            "config_dir": str(paths.config_dir()),
            "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }


def ensure_config_files() -> None:
    """Create the files a first run needs, without inventing any reader choices."""
    providers_cfg.ensure_file()
    loader.ensure_local_bundle()
