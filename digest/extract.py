"""Full-text extraction with trafilatura.

extract_pending(conn) fills `content` for items that have none.
Result semantics for each URL:
    str (maybe "")  final. "" = tried, nothing usable (404, PDF, blocked, ...)
    None            transient failure (timeout, 5xx, 429): left NULL, retried
                    next run, and expired to "" after 7 days by the db helper.
Network work runs in threads; all DB writes happen in the calling thread.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx
import trafilatura

from . import db

log = logging.getLogger(__name__)

MAX_WORDS = 6000
MAX_BYTES = 5_000_000
WORKERS = 8
RETRY_DAYS = 7
TRUNCATED_NOTE = "\n\n[Truncated. Read the full article at the source link.]"

# pages that never extract usefully
SKIP_HOSTS = {
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "news.ycombinator.com",
    "linkedin.com",
    "facebook.com",
    "reddit.com",
}


def _make_client() -> httpx.Client:
    return httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ai-digest/0.1; personal use)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )


def _truncate(text: str) -> str:
    words = list(re.finditer(r"\S+", text))
    if len(words) <= MAX_WORDS:
        return text
    return text[: words[MAX_WORDS - 1].end()] + TRUNCATED_NOTE


def extract_url(client: httpx.Client, url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return ""
    host = (parts.hostname or "").removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in SKIP_HOSTS):
        return ""
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        return None if code == 429 or code >= 500 else ""
    except httpx.TransportError:  # timeouts, connection errors
        return None
    except (httpx.RequestError, httpx.InvalidURL):  # e.g. redirect loop
        return ""

    ctype = resp.headers.get("content-type", "").lower()
    if ctype and not any(t in ctype for t in ("html", "xml", "text/plain")):
        return ""  # PDF, image, video, ...
    if len(resp.content) > MAX_BYTES:
        return ""
    try:
        text = trafilatura.extract(
            resp.content, url=url, include_comments=False, include_tables=True
        )
    except Exception as e:  # trafilatura should not kill the run
        log.warning("extract failed for %s: %s", url, e)
        return ""
    return _truncate(text or "")


def extract_pending(conn, limit: int = 200) -> dict:
    """Fetch + extract text for items with content NULL. Returns stats."""
    rows = db.items_missing_content(conn, limit)
    stats = {"extracted": 0, "empty": 0, "retry": 0, "expired": 0}
    if rows:
        with _make_client() as client, ThreadPoolExecutor(WORKERS) as pool:
            results = list(pool.map(lambda r: extract_url(client, r["url"]), rows))
        for row, text in zip(rows, results):
            if text is None:
                stats["retry"] += 1
                continue
            db.set_content(conn, row["id"], text)
            stats["extracted" if text else "empty"] += 1
    stats["expired"] = db.expire_missing_content(conn, RETRY_DAYS)
    log.info("extract: %s", stats)
    return stats
