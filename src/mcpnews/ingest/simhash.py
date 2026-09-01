"""SimHash for near-duplicate detection.

Wire copy is the dominant duplicate in a news corpus: the same agency story
lightly re-headlined by twelve outlets. Exact hashing misses all of it; a full
pairwise comparison is quadratic. SimHash over word shingles gets it in one
64-bit integer, and a Hamming distance of three or less is a reliable "these are
the same story".
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

_TOKEN = re.compile(r"\w+", re.UNICODE)
_SHINGLE = 3
_BITS = 64
_MASK = (1 << _BITS) - 1


def tokenise(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def shingles(tokens: list[str], size: int = _SHINGLE) -> list[str]:
    if len(tokens) < size:
        return [" ".join(tokens)] if tokens else []
    return [" ".join(tokens[i:i + size]) for i in range(len(tokens) - size + 1)]


def simhash(text: str) -> int:
    """A 64-bit fingerprint. Identical text gives an identical value everywhere.

    ``blake2b`` rather than ``hash()`` on purpose: Python's string hash is salted
    per process, so a fingerprint computed today would not match one computed
    after a restart.
    """
    grams = shingles(tokenise(text))
    if not grams:
        return 0
    vector = [0] * _BITS
    for gram, count in Counter(grams).items():
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(_BITS):
            vector[bit] += count if (value >> bit) & 1 else -count
    out = 0
    for bit in range(_BITS):
        if vector[bit] > 0:
            out |= 1 << bit
    return out & _MASK


def distance(a: int, b: int) -> int:
    return bin((a ^ b) & _MASK).count("1")
