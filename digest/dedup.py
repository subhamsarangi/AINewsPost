"""URL normalization + embedding-based clustering.

normalize_url     : canonical URL (ingesters use it as the unique key).
embed_pending     : create missing body + title embeddings.
cluster_new_items : attach new items to an existing story cluster, or start one.
"""

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import db, llm
from .config import get_settings

log = logging.getLogger(__name__)

EMBED_CHARS = 2000  # body embedding input: title + start of article
CLUSTER_WINDOW_DAYS = 14
EMBED_CHUNK = 200

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "igshid",
    "ref",
    "ref_src",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "yclid",
}


def normalize_url(url: str) -> str:
    """Canonical form of a URL, used as the unique key for items.

    https only, lowercase host, no www., no fragment, no tracking params,
    sorted query params, no trailing slash (except root).
    """
    url = (url or "").strip()
    if not url:
        return url
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return url
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"

    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    )
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, urlencode(query), ""))


def embed_pending(conn, max_items: int = 1000) -> dict:
    """Create missing embeddings. Returns {'body': n, 'title': m}.

    body : title + first 2000 chars of content. Used for search, similar items
           and interest matching. Needs content (possibly '').
    title: title only. Used for dedup clustering (sharper than body: the
           title names the event, the body adds topic noise).
    """
    counts = {"body": 0, "title": 0}
    while counts["body"] < max_items:
        rows = db.items_missing_embedding(conn, EMBED_CHUNK)
        if not rows:
            break
        texts = [
            f"{r['title'] or ''}\n{(r['content'] or '')[:EMBED_CHARS]}" for r in rows
        ]
        for row, vec in zip(rows, llm.embed(texts)):
            db.set_embedding(conn, row["id"], vec)
        counts["body"] += len(rows)
    while counts["title"] < max_items:
        rows = db.items_missing_title_embedding(conn, EMBED_CHUNK)
        if not rows:
            break
        for row, vec in zip(rows, llm.embed([r["title"] for r in rows])):
            db.set_title_embedding(conn, row["id"], vec)
        counts["title"] += len(rows)
    log.info("embedded: %s", counts)
    return counts


def cluster_new_items(conn, threshold: float | None = None) -> dict:
    """Assign cluster_id to every item with a title embedding and no cluster.

    Nearest already-clustered item in the last 14 days (by title embedding)
    with cosine similarity >= threshold: join its cluster. Otherwise the item
    starts its own cluster (cluster_id = its own id). Items are processed in id
    order and saved immediately, so later items in the same batch can match
    earlier ones.
    """
    threshold = get_settings().dedup_threshold if threshold is None else threshold
    stats = {"new_clusters": 0, "joined": 0}
    for row in db.items_unclustered(conn):
        near = db.nearest_recent(
            conn,
            row["title_embedding"],
            days=CLUSTER_WINDOW_DAYS,
            limit=1,
            exclude_id=row["id"],
        )
        if near and near[0]["similarity"] >= threshold:
            db.set_cluster(conn, row["id"], near[0]["cluster_id"])
            stats["joined"] += 1
        else:
            db.set_cluster(conn, row["id"], row["id"])
            stats["new_clusters"] += 1
    log.info("cluster: %s", stats)
    return stats
