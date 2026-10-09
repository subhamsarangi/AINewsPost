"""Postgres connection and ALL SQL helpers live here.

Usage:
    with connect() as conn:
        db.insert_item(conn, {...})
The context manager commits on success, rolls back on error, then closes.
"""

from datetime import date, datetime

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from .config import get_settings

Row = dict


def connect() -> psycopg.Connection:
    conn = psycopg.connect(get_settings().database_url, row_factory=dict_row)
    register_vector(conn)
    return conn


def _vec(v) -> np.ndarray:
    return np.asarray(v, dtype=np.float32)


def _np(v) -> np.ndarray | None:
    """Normalize whatever pgvector returns (ndarray or Vector) to a numpy array."""
    if v is None:
        return None
    return v.to_numpy() if hasattr(v, "to_numpy") else np.asarray(v, dtype=np.float32)


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
def sync_sources(conn, sources: list[dict]) -> None:
    """Mirror sources.yaml into the sources table (yaml stays the truth)."""
    for s in sources:
        conn.execute(
            """INSERT INTO sources (id, name, type, category)
               VALUES (%(id)s, %(name)s, %(type)s, %(category)s)
               ON CONFLICT (id) DO UPDATE
               SET name = EXCLUDED.name, type = EXCLUDED.type,
                   category = EXCLUDED.category""",
            s,
        )


def get_last_fetch(conn, source_id: str) -> datetime | None:
    row = conn.execute(
        "SELECT last_fetch_at FROM sources WHERE id = %s", (source_id,)
    ).fetchone()
    return row["last_fetch_at"] if row else None


def record_fetch(
    conn, source_id: str, status: str, item_count: int, success: bool = True
) -> None:
    """Log a fetch attempt. last_fetch_at only moves forward on success, so a
    failed run is retried from the same point (catch-up works)."""
    conn.execute(
        """UPDATE sources
           SET last_status = %s, last_item_count = %s,
               last_fetch_at = CASE WHEN %s THEN now() ELSE last_fetch_at END
           WHERE id = %s""",
        (status, item_count, success, source_id),
    )


def source_health(conn) -> list[Row]:
    return conn.execute(
        """SELECT s.*, count(i.id) AS total_items, max(i.fetched_at) AS last_new_item
           FROM sources s LEFT JOIN items i ON i.source_id = s.id
           GROUP BY s.id ORDER BY s.category, s.name"""
    ).fetchall()


# --------------------------------------------------------------------------
# Items: write path
# --------------------------------------------------------------------------
def insert_item(conn, item: dict) -> int | None:
    """Insert a new item. Returns its id, or None if canonical_url exists."""
    params = {
        "published_at": None,
        "content": None,
        "points": None,
        "num_comments": None,
        "hn_url": None,
        **item,
    }
    row = conn.execute(
        """INSERT INTO items (source_id, url, canonical_url, title, published_at,
                              content, points, num_comments, hn_url)
           VALUES (%(source_id)s, %(url)s, %(canonical_url)s, %(title)s,
                   %(published_at)s, %(content)s, %(points)s,
                   %(num_comments)s, %(hn_url)s)
           ON CONFLICT (canonical_url) DO NOTHING
           RETURNING id""",
        params,
    ).fetchone()
    return row["id"] if row else None


def update_hn_stats(conn, canonical_url: str, points: int, num_comments: int) -> None:
    conn.execute(
        "UPDATE items SET points = %s, num_comments = %s WHERE canonical_url = %s",
        (points, num_comments, canonical_url),
    )


def items_missing_content(conn, limit: int = 200) -> list[Row]:
    return conn.execute(
        """SELECT id, url FROM items
           WHERE content IS NULL ORDER BY fetched_at DESC LIMIT %s""",
        (limit,),
    ).fetchall()


def expire_missing_content(conn, days: int = 7) -> int:
    """Give up on items whose page never fetched: mark content '' so they still
    get embedded (by title) and stop being retried. Returns rows changed."""
    cur = conn.execute(
        """UPDATE items SET content = ''
           WHERE content IS NULL AND fetched_at < now() - make_interval(days => %s)""",
        (days,),
    )
    return cur.rowcount


def set_content(conn, item_id: int, content: str) -> None:
    # empty string (not NULL) marks "tried, nothing extracted" so we don't retry forever
    conn.execute("UPDATE items SET content = %s WHERE id = %s", (content, item_id))


def items_missing_embedding(conn, limit: int = 200) -> list[Row]:
    return conn.execute(
        """SELECT id, title, left(content, 6000) AS content FROM items
           WHERE embedding IS NULL AND content IS NOT NULL
           ORDER BY fetched_at DESC LIMIT %s""",
        (limit,),
    ).fetchall()


def set_embedding(conn, item_id: int, embedding) -> None:
    conn.execute(
        "UPDATE items SET embedding = %s WHERE id = %s", (_vec(embedding), item_id)
    )


def set_cluster(conn, item_id: int, cluster_id: int) -> None:
    conn.execute(
        "UPDATE items SET cluster_id = %s WHERE id = %s", (cluster_id, item_id)
    )


def set_summary(conn, item_id: int, summary: str) -> None:
    conn.execute("UPDATE items SET summary = %s WHERE id = %s", (summary, item_id))


def set_starred(conn, item_id: int, starred: bool) -> None:
    conn.execute("UPDATE items SET starred = %s WHERE id = %s", (starred, item_id))


# --------------------------------------------------------------------------
# Items: dedup + ranking reads
# --------------------------------------------------------------------------
def nearest_recent(
    conn, embedding, days: int = 14, limit: int = 5, exclude_id: int | None = None
) -> list[Row]:
    """Closest already-clustered items from the last `days`. similarity = cosine."""
    return conn.execute(
        """SELECT id, cluster_id, 1 - (embedding <=> %(e)s) AS similarity
           FROM items
           WHERE embedding IS NOT NULL AND cluster_id IS NOT NULL
             AND (%(ex)s::bigint IS NULL OR id <> %(ex)s)
             AND coalesce(published_at, fetched_at) >= now() - make_interval(days => %(d)s)
           ORDER BY embedding <=> %(e)s LIMIT %(n)s""",
        {"e": _vec(embedding), "ex": exclude_id, "d": days, "n": limit},
    ).fetchall()


def items_unclustered(conn) -> list[Row]:
    rows = conn.execute("""SELECT id, embedding FROM items
           WHERE embedding IS NOT NULL AND cluster_id IS NULL ORDER BY id""").fetchall()
    for r in rows:
        r["embedding"] = _np(r["embedding"])
    return rows


def rank_candidates(conn, since_hours: int = 36, limit: int = 80) -> list[Row]:
    """Cluster representatives from recent hours that haven't been in a digest lately."""
    rows = conn.execute(
        """SELECT i.id, i.title, i.source_id, s.category, i.points, i.num_comments,
                  i.published_at, i.embedding, left(i.content, 600) AS snippet
           FROM items i JOIN sources s ON s.id = i.source_id
           WHERE i.cluster_id = i.id AND i.embedding IS NOT NULL
             AND coalesce(i.published_at, i.fetched_at) >= now() - make_interval(hours => %s)
             AND i.id NOT IN (
                 SELECT di.item_id FROM digest_items di JOIN digests d ON d.id = di.digest_id
                 WHERE d.date >= current_date - 14)
           ORDER BY coalesce(i.published_at, i.fetched_at) DESC LIMIT %s""",
        (since_hours, limit),
    ).fetchall()
    for r in rows:
        r["embedding"] = _np(r["embedding"])
    return rows


def cluster_members(conn, cluster_id: int) -> list[Row]:
    return conn.execute(
        """SELECT i.id, i.title, i.url, i.source_id, s.name AS source_name
           FROM items i JOIN sources s ON s.id = i.source_id
           WHERE i.cluster_id = %s ORDER BY i.id""",
        (cluster_id,),
    ).fetchall()


# --------------------------------------------------------------------------
# Items: UI reads
# --------------------------------------------------------------------------
def get_item(conn, item_id: int) -> Row | None:
    return conn.execute(
        """SELECT i.id, i.source_id, s.name AS source_name, s.category, i.url,
                  i.title, i.published_at, i.fetched_at, i.content, i.summary,
                  i.points, i.num_comments, i.hn_url, i.cluster_id, i.starred
           FROM items i JOIN sources s ON s.id = i.source_id WHERE i.id = %s""",
        (item_id,),
    ).fetchone()


def get_embedding(conn, item_id: int):
    row = conn.execute(
        "SELECT embedding FROM items WHERE id = %s", (item_id,)
    ).fetchone()
    return _np(row["embedding"]) if row else None


def similar_items(conn, item_id: int, limit: int = 5) -> list[Row]:
    return conn.execute(
        """SELECT b.id, b.title, b.source_id, 1 - (b.embedding <=> a.embedding) AS similarity
           FROM items a JOIN items b ON b.id <> a.id
           WHERE a.id = %s AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
           ORDER BY b.embedding <=> a.embedding LIMIT %s""",
        (item_id, limit),
    ).fetchall()


_SORTS = {
    "date": "coalesce(i.published_at, i.fetched_at) DESC",
    "points": "i.points DESC NULLS LAST, coalesce(i.published_at, i.fetched_at) DESC",
}


def list_items(
    conn,
    source_id: str | None = None,
    category: str | None = None,
    since: datetime | None = None,
    starred: bool | None = None,
    sort: str = "date",
    limit: int = 20,
    offset: int = 0,
) -> list[Row]:
    """Browse mode (no search query). All filters optional."""
    where, params = ["true"], {"limit": limit, "offset": offset}
    if source_id:
        where.append("i.source_id = %(source_id)s")
        params["source_id"] = source_id
    if category:
        where.append("s.category = %(category)s")
        params["category"] = category
    if since:
        where.append("coalesce(i.published_at, i.fetched_at) >= %(since)s")
        params["since"] = since
    if starred is not None:
        where.append("i.starred = %(starred)s")
        params["starred"] = starred
    order = _SORTS.get(sort, _SORTS["date"])
    return conn.execute(
        f"""SELECT i.id, i.source_id, s.name AS source_name, s.category, i.title,
                   i.url, i.published_at, i.points, i.num_comments, i.starred,
                   left(coalesce(i.summary, i.content, ''), 300) AS snippet
            FROM items i JOIN sources s ON s.id = i.source_id
            WHERE {' AND '.join(where)}
            ORDER BY {order} LIMIT %(limit)s OFFSET %(offset)s""",
        params,
    ).fetchall()


# --------------------------------------------------------------------------
# Digests
# --------------------------------------------------------------------------
def save_digest(conn, digest_date: date, pdf_path: str, item_ids: list[int]) -> int:
    """Create (or replace) the digest for a date and its ranked items."""
    row = conn.execute(
        """INSERT INTO digests (date, pdf_path) VALUES (%s, %s)
           ON CONFLICT (date) DO UPDATE SET pdf_path = EXCLUDED.pdf_path
           RETURNING id""",
        (digest_date, pdf_path),
    ).fetchone()
    digest_id = row["id"]
    conn.execute("DELETE FROM digest_items WHERE digest_id = %s", (digest_id,))
    for rank, item_id in enumerate(item_ids, start=1):
        conn.execute(
            "INSERT INTO digest_items (digest_id, item_id, rank) VALUES (%s, %s, %s)",
            (digest_id, item_id, rank),
        )
    return digest_id


def list_digests(conn, limit: int = 60) -> list[Row]:
    return conn.execute(
        """SELECT d.id, d.date, d.pdf_path, count(di.item_id) AS n_items
           FROM digests d LEFT JOIN digest_items di ON di.digest_id = d.id
           GROUP BY d.id ORDER BY d.date DESC LIMIT %s""",
        (limit,),
    ).fetchall()


def digest_items(conn, digest_id: int) -> list[Row]:
    return conn.execute(
        """SELECT di.rank, i.id, i.title, i.source_id
           FROM digest_items di JOIN items i ON i.id = di.item_id
           WHERE di.digest_id = %s ORDER BY di.rank""",
        (digest_id,),
    ).fetchall()
