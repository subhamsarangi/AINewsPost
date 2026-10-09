"""Hybrid search: Postgres FTS + pgvector merged with Reciprocal Rank Fusion.

Used by the CLI and the Streamlit UI. Empty query = browse mode (latest or
top-points first). With a query, results are ordered by relevance and `sort`
is ignored.
"""

import logging
from datetime import datetime
from functools import lru_cache

from . import db, llm

log = logging.getLogger(__name__)

MIN_SIMILARITY = 0.26  # vector leg cutoff; raise if results are noisy


@lru_cache(maxsize=256)
def _embed_query(query: str) -> tuple[float, ...] | None:
    """Cached so 'load more' and repeated searches cost no extra API calls.
    Returns None if embedding fails: search degrades to keyword-only."""
    try:
        return tuple(llm.embed_one(query))
    except Exception as e:
        log.warning("query embedding failed, keyword-only search: %s", e)
        return None


def search(
    conn,
    query: str = "",
    source_id: str | None = None,
    category: str | None = None,
    since: datetime | None = None,
    starred: bool | None = None,
    sort: str = "date",
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return db.list_items(
            conn,
            source_id=source_id,
            category=category,
            since=since,
            starred=starred,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    return db.hybrid_search(
        conn,
        query,
        embedding=_embed_query(query),
        source_id=source_id,
        category=category,
        since=since,
        starred=starred,
        limit=limit,
        offset=offset,
        min_similarity=MIN_SIMILARITY,
    )
