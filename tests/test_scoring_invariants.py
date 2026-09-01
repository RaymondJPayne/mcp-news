"""These tests exist to stop a specific regression.

If someone applies recency decay inside the scorer, historical articles score
near zero no matter how well they match, and every backfill silently produces
an empty result set. It is an easy mistake to make and a hard one to notice.
"""
import pytest


@pytest.mark.xfail(reason="scorer lands in phase 2", strict=False)
def test_score_is_independent_of_publication_date():
    """The same article must score identically whether it is an hour or a year old."""
    raise NotImplementedError


@pytest.mark.xfail(reason="scorer lands in phase 2", strict=False)
def test_tier_zero_scoring_needs_no_provider():
    """Scoring must work with no chat or embed provider configured at all."""
    raise NotImplementedError
