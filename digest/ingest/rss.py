"""feedparser-based fetcher for blogs, newsletters and labs with RSS.

Pure fetcher: returns item dicts, never touches the DB.
Optional per-source keys in sources.yaml:
    max_age_days: 14   # never look further back than this (default 14)
    max_items: 30      # newest N per run (default 30)
"""

import calendar
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from selectolax.lexbor import LexborHTMLParser

from ..dedup import normalize_url

log = logging.getLogger(__name__)

FULL_TEXT_MIN_CHARS = 1500  # feed body this long = treat as full article
DEFAULT_MAX_AGE_DAYS = 14
DEFAULT_MAX_ITEMS = 30
OVERLAP = timedelta(days=1)  # re-check a day back; insert dedups on URL


def _make_client() -> httpx.Client:
    return httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "ai-digest/0.1 (personal feed reader)"},
    )


def _html_to_text(raw: str) -> str:
    raw = re.sub(
        r"</(p|div|h[1-6]|li|blockquote|pre|tr)>|<br\s*/?>",
        "\n\n",
        raw or "",
        flags=re.I,
    )
    tree = LexborHTMLParser(raw)
    for node in tree.css("script,style"):
        node.decompose()
    lines = [ln.strip() for ln in (tree.text() or "").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _published(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    # feedparser returns UTC struct_time; timegm treats it as UTC
    return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)


def _body(entry) -> str | None:
    """Full text if the feed carries it, else None (extract.py fetches the page)."""
    raw = ""
    if entry.get("content"):
        raw = entry["content"][0].get("value", "")
    raw = raw or entry.get("summary", "")
    text = _html_to_text(raw)
    return text if len(text) >= FULL_TEXT_MIN_CHARS else None


def fetch(source: dict, since: datetime | None = None) -> list[dict]:
    now = datetime.now(timezone.utc)
    max_age = now - timedelta(days=source.get("max_age_days", DEFAULT_MAX_AGE_DAYS))
    cutoff = max(since - OVERLAP, max_age) if since else max_age
    max_items = source.get("max_items", DEFAULT_MAX_ITEMS)

    with _make_client() as client:
        resp = client.get(source["url"])
        resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries and feed.get("bozo"):
        raise ValueError(
            f"unparseable feed {source['url']}: {feed.get('bozo_exception')}"
        )

    items = []
    for e in feed.entries:
        link, title = e.get("link"), (e.get("title") or "").strip()
        if not link or not title:
            continue
        published = _published(e)
        if published and published < cutoff:
            continue  # undated entries pass; insert dedups them
        items.append(
            {
                "source_id": source["id"],
                "url": link,
                "canonical_url": normalize_url(link),
                "title": title,
                "published_at": published,
                "content": _body(e),
                "points": None,
                "num_comments": None,
                "hn_url": None,
            }
        )

    items.sort(key=lambda i: i["published_at"] or now, reverse=True)
    return items[:max_items]
