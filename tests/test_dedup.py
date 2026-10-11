"""Tests for the riskiest pure logic: URL normalization (dedup key).

Run from the project root:  uv run pytest -q   (pytest is optional: uv add --dev pytest)
"""

import pytest

from digest.dedup import normalize_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "http://www.Example.com/a/b/?utm_source=x&b=2&a=1#frag",
            "https://example.com/a/b?a=1&b=2",
        ),
        ("https://example.com/", "https://example.com"),
        ("example.com/x?fbclid=1", "https://example.com/x"),
        ("https://example.com:8080/p", "https://example.com:8080/p"),
        ("https://x.com/a?id=5&ref=hn", "https://x.com/a?id=5"),
        (
            "https://techgig.com/news/ai/x/1?mailer_id=0&dt=2026-10-11",
            "https://techgig.com/news/ai/x/1?dt=2026-10-11&mailer_id=0",
        ),
        ("", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize_url(raw) == expected


def test_same_article_different_tracking_is_one_key():
    a = normalize_url("https://site.com/post?utm_source=newsletter&utm_medium=email")
    b = normalize_url("https://www.site.com/post/?utm_source=twitter#comments")
    assert a == b
