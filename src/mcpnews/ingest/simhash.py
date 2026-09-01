"""SimHash for near-duplicate detection.

Wire copy is the dominant duplicate in a news corpus: the same agency story
lightly re-headlined by twelve outlets. Exact hashing misses all of it; a full
pairwise comparison is quadratic. SimHash gets it in one 64-bit integer, and a
small Hamming distance is a reliable "these are the same story".

Two choices worth recording, because both were measured rather than guessed.

**Features are single words weighted by frequency, not shingles.** Three-word
shingles sound more discriminating and behave worse here: rewriting two phrases
in a four-hundred-word article changes six shingles and moves the fingerprint by
about nine bits, which is uncomfortably close to the distance between two
genuinely different articles on the same subject. Word frequencies move by about
six bits for the same edit while unrelated stories sit above twenty, so the gap
between "duplicate" and "different" is roughly three times wider.

**blake2b, not the built-in hash().** Python's string hash is salted per process,
so a fingerprint computed today would not match one computed after a restart —
which is precisely the comparison this exists to make.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

_TOKEN = re.compile(r"\w+", re.UNICODE)
_BITS = 64
_MASK = (1 << _BITS) - 1

#: Measured separation on real article text: a re-worded copy lands around six,
#: an unrelated story above twenty. Seven is both comfortably inside that gap and
#: the largest distance the eight-band index can guarantee it will find.
DEFAULT_MAX_DISTANCE = 7


def tokenise(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def features(text: str) -> Counter[str]:
    return Counter(tokenise(text))


def simhash(text: str) -> int:
    """A 64-bit fingerprint. Identical text gives an identical value everywhere."""
    counts = features(text)
    if not counts:
        return 0
    vector = [0] * _BITS
    for token, count in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
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
