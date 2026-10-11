"""Selector-based scraper (selectolax) for listing pages without a feed.

Pure fetcher: returns item dicts, never touches the DB. One entry in sources.yaml:

    - id: anthropic
      type: scrape
      url: https://www.anthropic.com/research
      selectors:
        item:  'a[class*="PublicationList"][class*="listItem"]'   # one match per article card
        link:  self                    # 'self' = the item is the <a>; else a selector inside it
        title: '[class*="title"]'      # selector inside the item (falls back to link aria-label)
        date:  time                    # optional; text or datetime attribute
        link_param: url                # optional: real article URL is a query parameter of the
                                       #   link (tracking redirects in email-style newsletters)
        date_param: dt                 # optional: date taken from a query parameter of the link
      render: http                     # optional: 'browser' loads the page in Chromium (JS sites)
      max_age_days: 14                 # optional, default 14
      max_items: 30                    # optional, default 30

Page text is NOT stored here (content = None): extract.py fetches each article.
A listing that yields zero items raises, so a changed page layout shows up in the
source health line instead of silently returning nothing.
"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser

from ..dedup import normalize_url

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; ai-digest/0.1; personal use)"
DEFAULT_MAX_AGE_DAYS = 14
DEFAULT_MAX_ITEMS = 30
OVERLAP = timedelta(days=1)
DATE_FORMATS = (
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y-%m-%d",
    "%b %d %Y",
)


def _make_client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA})


# --------------------------------------------------------------------------
# Getting the HTML
# --------------------------------------------------------------------------
def _render_browser(url: str, wait_for: str) -> str:
    """For pages whose list is built by JavaScript: load in Chromium, wait for items."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(user_agent=UA)
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_selector(wait_for, timeout=15_000)
                return page.content()
            finally:
                browser.close()
    except PlaywrightError as e:
        if "playwright install" in str(e) or "Executable doesn't exist" in str(e):
            raise RuntimeError(
                "Chromium is not installed. " "Run: uv run playwright install chromium"
            ) from e
        raise


def _get_html(source: dict) -> str:
    if source.get("render") == "browser":
        return _render_browser(source["url"], source["selectors"]["item"])
    with _make_client() as client:
        resp = client.get(source["url"])
        resp.raise_for_status()
    return resp.text


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _parse_date(text: str | None) -> datetime | None:
    text = " ".join((text or "").split())
    if not text:
        return None
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _query_param(href: str, name: str) -> str | None:
    values = parse_qs(urlsplit(href).query).get(name)
    return values[0] if values else None


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _parse_item(node, sel: dict, base_url: str) -> dict | None:
    """-> {'url','title','published'} or None if the card has no usable link/title."""
    link_sel = sel.get("link", "self")
    link = node if link_sel == "self" else node.css_first(link_sel)
    raw_href = (link.attributes.get("href") if link is not None else None) or ""
    raw_href = raw_href.strip()
    if not raw_href:
        return None
    href = raw_href
    if sel.get("link_param"):  # unwrap tracking redirects: ...?url=<real>&...
        href = _query_param(raw_href, sel["link_param"]) or raw_href

    title_node = node.css_first(sel["title"])
    title = _clean(title_node.text()) if title_node is not None else ""
    title = title or _clean(link.attributes.get("aria-label"))
    if not title:
        return None

    published = None
    if sel.get("date_param"):
        published = _parse_date(_query_param(raw_href, sel["date_param"]))
    if published is None and sel.get("date"):
        dnode = node.css_first(sel["date"])
        if dnode is not None:
            published = _parse_date(dnode.attributes.get("datetime")) or _parse_date(
                dnode.text()
            )
    return {"url": urljoin(base_url, href), "title": title, "published": published}


def fetch(source: dict, since: datetime | None = None) -> list[dict]:
    sel = source.get("selectors") or {}
    for key in ("item", "title"):
        if not sel.get(key) or str(sel[key]).strip().upper() == "TODO":
            raise ValueError(
                f"source '{source['id']}': selectors.{key} is not filled in "
                "in sources.yaml"
            )

    tree = LexborHTMLParser(_get_html(source))
    nodes = tree.css(sel["item"])
    if not nodes:
        raise ValueError(
            f"no items matched selector {sel['item']!r} on {source['url']}. The page layout "
            "may have changed"
            + (
                ""
                if source.get("render") == "browser"
                else ", or the list is built by JavaScript (try `render: browser`)"
            )
        )

    now = datetime.now(timezone.utc)
    max_age = now - timedelta(days=source.get("max_age_days", DEFAULT_MAX_AGE_DAYS))
    cutoff = max(since - OVERLAP, max_age) if since else max_age

    items, seen = [], set()
    for node in nodes:
        parsed = _parse_item(node, sel, source["url"])
        if not parsed:
            continue
        canonical = normalize_url(parsed["url"])
        if canonical in seen:  # featured card repeated in the list
            continue
        seen.add(canonical)
        pub = parsed["published"]
        if pub and pub < cutoff:
            continue  # undated items pass; insert dedups on URL
        items.append(
            {
                "source_id": source["id"],
                "url": parsed["url"],
                "canonical_url": canonical,
                "title": parsed["title"],
                "published_at": pub,
                "content": None,  # extract.py fetches the article page
                "points": None,
                "num_comments": None,
                "hn_url": None,
            }
        )

    if not items and len(seen) == 0:
        raise ValueError(
            f"items matched on {source['url']} but none had a link and title; "
            "check selectors.link / selectors.title"
        )
    items.sort(key=lambda i: i["published_at"] or now, reverse=True)
    return items[: source.get("max_items", DEFAULT_MAX_ITEMS)]
