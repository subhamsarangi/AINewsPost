"""Orchestrates the daily run: ingest, extract, embed, cluster, rank, summarize, pdf, save.

Only this file knows the order of the stages. Every stage is idempotent and
commits on its own, so a crash loses nothing already done and a rerun resumes.
"""

import asyncio
import logging
from datetime import date

from . import db, dedup, extract, llm, rank
from .config import DIGEST_DIR, ROOT, load_sources
from .ingest import hn, rss

log = logging.getLogger(__name__)

FETCHERS = {"rss": rss.fetch, "hn": hn.fetch}

NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "openai",
    "urllib3",
    "trafilatura",
    "courlan",
    "htmldate",
    "justext",
    "charset_normalizer",
)


def _setup_logging() -> None:
    """Progress lines on stderr. force=True because some libraries install a root
    handler on import, which would silently turn basicConfig into a no-op."""
    logging.basicConfig(
        level=logging.INFO,
        force=True,
        datefmt="%H:%M:%S",
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    for name in NOISY_LOGGERS:  # one line per HTTP request is too much
        logging.getLogger(name).setLevel(logging.WARNING)


def _fetcher(source: dict):
    if source["type"] == "scrape":  # scrape.py is written last; may not exist yet
        from .ingest import scrape

        return getattr(scrape, "fetch", None)
    return FETCHERS.get(source["type"])


# --------------------------------------------------------------------------
# Stage: ingest (one source failing never stops the others)
# --------------------------------------------------------------------------
async def _ingest_source(source: dict, admin_id: str) -> dict:
    sid = source["id"]
    fetch = _fetcher(source)
    if fetch is None:
        log.warning(
            "source '%s': no fetcher for type '%s', skipped", sid, source["type"]
        )
        return {"id": sid, "new": 0, "error": "no fetcher"}

    log.info("  fetching '%s' ...", sid)
    with db.connect() as conn:
        since = db.get_last_fetch(conn, sid)
    try:
        items = await fetch(source, since)  # pure: network only, no DB
    except Exception as e:
        msg = f"error: {type(e).__name__}: {e}"[:300]
        log.warning("source '%s' failed: %s", sid, msg)
        with db.connect() as conn:
            db.record_fetch(conn, sid, msg, 0, success=False)
        return {"id": sid, "new": 0, "error": msg}

    new = 0
    with db.connect() as conn:
        for item in items:
            if db.insert_item(conn, item, owner_id=admin_id) is not None:
                new += 1
            elif item.get("points") is not None:  # known HN story: refresh counts
                db.update_hn_stats(
                    conn, item["canonical_url"], item["points"], item["num_comments"]
                )
        db.record_fetch(conn, sid, f"ok, {new} new of {len(items)}", len(items))
    log.info("  '%s': %d new of %d fetched", sid, new, len(items))
    return {"id": sid, "new": new, "error": None}


# --------------------------------------------------------------------------
# Stage: process new items (text, embeddings, clusters)
# --------------------------------------------------------------------------
def _process_new_items() -> None:
    for _ in range(5):  # 200 pages per pass
        with db.connect() as conn:
            st = extract.extract_pending(conn)
        if st["extracted"] + st["empty"] == 0:
            break
    with db.connect() as conn:
        dedup.embed_pending(conn)
        dedup.cluster_new_items(conn)


# --------------------------------------------------------------------------
# Stage: summarize the picks (only these, never the whole candidate pool)
# --------------------------------------------------------------------------
def _hn_comments(item: dict) -> list[str] | None:
    sid = hn.story_id_from_url(item.get("hn_url"))
    if not sid:
        return None
    try:
        return hn.fetch_top_comments(sid) or None
    except Exception as e:
        log.warning("HN comments failed for item %s: %s", item["id"], e)
        return None


def _build_items(picks: list[dict]) -> list[dict]:
    """Full item dicts for the PDF, in rank order. Summaries are saved, so a
    rerun (or --force) never pays for the same summary twice."""
    items = []
    for n, pick in enumerate(picks, start=1):
        with db.connect() as conn:
            item = db.get_item(conn, pick["id"])
            log.info(
                "  %d/%d %s%s",
                n,
                len(picks),
                item["title"][:70],
                "  (summary cached)" if item["summary"] else "",
            )
            if not item["summary"]:
                try:
                    item["summary"] = llm.summarize(
                        item["title"], item["content"], _hn_comments(item)
                    )
                    db.set_summary(conn, item["id"], item["summary"])
                except Exception as e:
                    if llm.is_fatal(e):
                        raise
                    log.error("summary failed for item %s: %s", item["id"], e)
            item["reason"] = pick["reason"]
            item["also_covered"] = [
                m
                for m in db.cluster_members(conn, item["cluster_id"])
                if m["id"] != item["id"]
            ]
        items.append(item)
    return items


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------
async def run(
    dry_run: bool = False,
    no_fetch: bool = False,
    force: bool = False,
    today: date | None = None,
) -> dict:
    """One full daily run (see _run). Database trouble becomes db.DatabaseProblem
    with a message that says how to fix it; callers print it, no traceback."""
    _setup_logging()
    db.check()  # fail fast: before any network work
    try:
        return await _run(dry_run=dry_run, no_fetch=no_fetch, force=force, today=today)
    except db.CONNECTION_ERRORS as e:  # connection dropped mid-run
        raise db.DatabaseProblem(db.explain(e)) from e


async def _run(
    dry_run: bool = False,
    no_fetch: bool = False,
    force: bool = False,
    today: date | None = None,
) -> dict:
    """One full daily run.

    dry_run : stop after ranking (no summaries, no PDF, nothing saved). Shows picks.
    no_fetch: skip source fetching (re-process and re-rank what is in the DB).
    force   : rebuild today's digest even if one exists.
    """
    today = today or date.today()
    result = {
        "date": today.isoformat(),
        "sources": [],
        "picks": [],
        "pdf": None,
        "note": None,
    }

    with db.connect() as conn:
        admin_id = db.ensure_admin_user(conn)
        db.sync_sources(conn, load_sources(include_todo=True), owner_id=admin_id)
        existing = db.get_digest(conn, today)
    if existing and not dry_run and not force:
        result.update(
            pdf=existing["pdf_path"], note="digest for today exists (use --force)"
        )
        log.info(result["note"])
        return result

    if no_fetch:
        log.info("[1/5] fetching skipped (--no-fetch)")
    else:
        sources = load_sources()
        log.info("[1/5] fetching %d sources", len(sources))
        result["sources"] = await asyncio.gather(
            *[_ingest_source(s, admin_id) for s in sources]
        )
    log.info("[2/5] extracting page text, embedding, clustering")
    _process_new_items()
    log.info("[3/5] ranking candidates")

    restore = None  # --force: old digest, put back on failure
    try:
        with db.connect() as conn:
            if existing and not dry_run:  # free today's items for re-ranking
                restore = (
                    existing["pdf_path"],
                    [r["id"] for r in db.digest_items(conn, existing["id"])],
                )
                db.delete_digest(conn, today)
            picks = rank.select(conn)
            result["picks"] = [
                {
                    "id": p["id"],
                    "reason": p["reason"],
                    "title": db.get_item(conn, p["id"])["title"],
                }
                for p in picks
            ]
        log.info("  picked %d item(s)", len(picks))
        if not picks:
            _restore(today, restore, admin_id)
            result["note"] = "nothing worth reading: no digest written"
            log.info(result["note"])
            return result
        if dry_run:
            result["note"] = "dry run: stopped after ranking"
            return result

        if any(p["reason"].startswith("fallback") for p in picks):
            result["note"] = (
                "AI ranking failed (see log); these picks are the top items by "
                "interest score instead."
            )
        log.info("[4/5] summarizing %d picks", len(picks))
        items = _build_items(picks)

        log.info("[5/5] rendering PDF")
        from . import pdf  # imported late: heavy (Playwright)

        pdf_url = await pdf.render(today, items)
        with db.connect() as conn:
            db.save_digest(conn, today, pdf_url, [i["id"] for i in items], owner_id=admin_id)
    except Exception:
        _restore(today, restore, admin_id)
        raise
    result["pdf"] = pdf_url
    log.info("digest saved: %s", pdf_url)
    log.info(llm.usage_report())
    return result


def _restore(today: date, restore: tuple[str, list[int]] | None, admin_id: str | None = None) -> None:
    """A failed --force rerun must not destroy the digest that already existed."""
    if not restore:
        return
    try:
        with db.connect() as conn:
            db.save_digest(conn, today, restore[0], restore[1], owner_id=admin_id)
    except (db.DatabaseProblem, *db.CONNECTION_ERRORS):
        log.error(
            "could not restore today's digest row (database down). The PDF is "
            "still at %s; rerun with --force to rebuild.",
            restore[0],
        )
