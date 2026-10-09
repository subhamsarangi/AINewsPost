"""Hacker News via Algolia: stories (points/num_comments) + top comments fetch.

Pure fetcher: returns item dicts, never touches the DB.
"""

import html
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from ..config import get_settings
from ..dedup import normalize_url

log = logging.getLogger(__name__)

API = "https://hn.algolia.com/api/v1"
HN_ITEM = "https://news.ycombinator.com/item?id={}"
MIN_LOOKBACK = timedelta(hours=48)  # stories get 2 days to reach the points bar
MAX_LOOKBACK = timedelta(days=7)
MIN_COMMENT_CHARS = 80


def _make_client() -> httpx.Client:
    return httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "ai-digest/0.1 (personal)"},
    )


def _clean_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<p>|<br\s*/?>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _lookback(since: datetime | None) -> timedelta:
    now = datetime.now(timezone.utc)
    lb = (now - since) if since else MIN_LOOKBACK
    return min(max(lb, MIN_LOOKBACK), MAX_LOOKBACK)


def _to_item(hit: dict, source_id: str) -> dict | None:
    title = hit.get("title")
    if not title:
        return None
    hn_url = HN_ITEM.format(hit["objectID"])
    url = hit.get("url") or hn_url
    # Ask HN / text posts: body is the content, no page to extract later
    content = None
    if not hit.get("url"):
        content = _clean_html(hit.get("story_text")) or None
    return {
        "source_id": source_id,
        "url": url,
        "canonical_url": normalize_url(url),
        "title": title,
        "published_at": datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc),
        "content": content,
        "points": hit.get("points"),
        "num_comments": hit.get("num_comments"),
        "hn_url": hn_url,
    }


def fetch(source: dict, since: datetime | None = None) -> list[dict]:
    """Stories above the points bar matching any keyword in source['keywords'].

    Looks back at least 48h even if `since` is recent, because points grow
    after posting. Re-seen stories are harmless: insert dedups on URL and the
    pipeline refreshes their points.
    """
    min_points = source.get("min_points") or get_settings().hn_min_points
    cutoff = int((datetime.now(timezone.utc) - _lookback(since)).timestamp())
    keywords = source.get("keywords") or [""]

    hits: dict[str, dict] = {}
    errors: list[Exception] = []
    with _make_client() as client:
        for kw in keywords:
            try:
                resp = client.get(
                    f"{API}/search_by_date",
                    params={
                        "query": kw,
                        "tags": "story",
                        "numericFilters": f"points>={min_points},created_at_i>{cutoff}",
                        "hitsPerPage": 100,
                    },
                )
                resp.raise_for_status()
                for hit in resp.json().get("hits", []):
                    hits.setdefault(hit["objectID"], hit)
            except (httpx.HTTPError, ValueError) as e:
                log.warning("hn keyword %r failed: %s", kw, e)
                errors.append(e)
    if errors and len(errors) == len(keywords):
        raise errors[-1]  # everything failed: let the pipeline mark the source failed

    items = [i for h in hits.values() if (i := _to_item(h, source["id"]))]
    items.sort(key=lambda i: i["published_at"], reverse=True)
    return items


# --------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------
def _subtree_size(node: dict) -> int:
    count, stack = 0, list(node.get("children") or [])
    while stack:
        n = stack.pop()
        count += 1
        stack.extend(n.get("children") or [])
    return count


def fetch_top_comments(story_id: int | str, n: int = 3) -> list[str]:
    """Top-level comments ranked by reply-subtree size (HN hides comment scores).

    Short comments are dropped. Returns cleaned plain text, best first.
    """
    with _make_client() as client:
        resp = client.get(f"{API}/items/{story_id}")
        resp.raise_for_status()
        children = resp.json().get("children") or []

    scored = []
    for order, c in enumerate(children):
        text = _clean_html(c.get("text"))
        if len(text) >= MIN_COMMENT_CHARS:
            scored.append((_subtree_size(c), len(text), -order, text))
    scored.sort(reverse=True)
    return [s[3] for s in scored[:n]]


def story_id_from_url(hn_url: str) -> str | None:
    m = re.search(r"id=(\d+)", hn_url or "")
    return m.group(1) if m else None
