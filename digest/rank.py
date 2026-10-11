"""Cheap pre-filter, then one LLM call to pick up to 5.

prefilter(conn) : score candidates without any API call (free to run, good for tuning).
select(conn)    : prefilter, then llm.pick_top. Returns [{'id', 'reason'}, ...].
"""

import hashlib
import logging
import math
from datetime import date, datetime, timezone

import numpy as np

from . import db, llm
from .config import OUTPUT_DIR, get_settings

log = logging.getLogger(__name__)

INTEREST = (
    "LLM evals and observability, LLM pricing, agent tooling, AI Benchmarks, "
    "AI cybersecurity, RAG, MCP, MLOps, Gen AI job market, Gen AI upskilling, "
    "AI research papers, frontier model releases, open-source models, "
    "startup funding rounds in AI"
)

KEEP = 30  # candidates sent to the LLM
FALLBACK_N = 3  # picks if the LLM call fails
W_RECENCY = 0.08  # score bonus for fresh items (decays with age)
RECENCY_TAU_H = 24
W_POINTS = 0.05  # score bonus for HN points (capped)
POINTS_CAP = 500


def _interest_vector() -> np.ndarray:
    """Embedding of INTEREST, cached on disk (re-embedded only if text or model changes)."""
    key = hashlib.sha1(f"{get_settings().embed_model}|{INTEREST}".encode()).hexdigest()[
        :12
    ]
    path = OUTPUT_DIR / f"interest_{key}.npy"
    if path.exists():
        return np.load(path)
    vec = np.asarray(llm.embed_one(INTEREST), dtype=np.float32)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    np.save(path, vec)
    return vec


def _window_hours(conn) -> int:
    """How far back to look: since the last digest (+36h buffer), 36h to 7 days.
    First ever run: 72h."""
    last = db.list_digests(conn, 1)
    if not last:
        return 72
    days = (date.today() - last[0]["date"]).days
    return min(max(days * 24 + 36, 36), 168)


def _score(c: dict, ivec: np.ndarray, now: datetime) -> tuple[float, float]:
    emb = c["embedding"]
    sim = float(emb @ ivec / (np.linalg.norm(emb) * np.linalg.norm(ivec)))
    pub = c["published_at"]
    age_h = max((now - pub).total_seconds() / 3600, 0) if pub else 12.0
    recency = math.exp(-age_h / RECENCY_TAU_H)
    points = min(c.get("points") or 0, POINTS_CAP) / POINTS_CAP
    return sim + W_RECENCY * recency + W_POINTS * points, sim


def prefilter(conn, since_hours: int | None = None) -> list[dict]:
    """Top KEEP candidates by interest similarity + recency + HN points. No API calls
    (apart from embedding INTEREST once). Each row gets 'score' and 'sim'."""
    hours = since_hours or _window_hours(conn)
    cands = db.rank_candidates(conn, since_hours=hours, limit=200)
    min_points = get_settings().hn_min_points
    cands = [c for c in cands if c["points"] is None or c["points"] >= min_points]
    if not cands:
        return []
    ivec, now = _interest_vector(), datetime.now(timezone.utc)
    for c in cands:
        c["score"], c["sim"] = _score(c, ivec, now)
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands[:KEEP]


def select(conn, since_hours: int | None = None) -> list[dict]:
    """Pick up to DIGEST_MAX_ITEMS items. [] means nothing worth reading today.

    If the LLM call fails for a transient reason (network, server error, unparseable
    output), falls back to the top FALLBACK_N by prefilter score so a bad day still
    produces a digest. Configuration/billing errors (llm.is_fatal) are raised.
    """
    top = prefilter(conn, since_hours)
    if not top:
        log.info("rank: no candidates in window")
        return []
    max_items = get_settings().digest_max_items
    try:
        picks = llm.pick_top(top, INTEREST, max_items)
    except Exception as e:
        if llm.is_fatal(e):  # bad key / model / quota: do not fake a digest
            raise
        log.error(
            "rank: LLM pick failed (%s); falling back to top %d by score", e, FALLBACK_N
        )
        return [
            {"id": c["id"], "reason": "fallback: top by interest score"}
            for c in top[: min(FALLBACK_N, max_items)]
        ]
    if not picks:
        log.info("rank: LLM found nothing worth reading among %d candidates", len(top))
    return picks
