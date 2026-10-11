"""feed_view(): the one view every page uses (unified, starred, per source), and item_detail()."""

import re
from datetime import datetime, timedelta, timezone

import streamlit as st
from streamlit_scroll_to_top import scroll_to_here

from digest import db, search
from digest.config import CATEGORIES, load_sources

PAGE_SIZE = 20
DATE_OPTIONS = {
    "Any time": None,
    "Last 24 hours": 24,
    "Last 7 days": 24 * 7,
    "Last 30 days": 24 * 30,
}
SORT_OPTIONS = {"Newest": "date", "Most points": "points"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def run_db(fn, *args, **kwargs):
    """Run fn(conn, ...) with a fresh connection; show a message, not a traceback."""
    try:
        with db.connect() as conn:
            return fn(conn, *args, **kwargs)
    except db.DatabaseProblem as e:
        st.error(str(e))
        st.stop()
    except db.CONNECTION_ERRORS as e:
        st.error(db.explain(e))
        st.stop()


def scroll_to_top():
    """Scroll to top using the streamlit-scroll-to-top component."""
    if st.session_state.get("_should_scroll_top"):
        scroll_to_here(0, key=f"top_{st.session_state.get('_scroll_key', 0)}")
        st.session_state["_should_scroll_top"] = False


def esc(text: str | None) -> str:
    """Escape markdown/latex/emoji-shortcode characters so scraped text renders literally."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$:])", r"\\\1", text or "")


def _date(d: datetime | None) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ") if d else ""


def render_summary(summary: str) -> None:
    """Summary markdown; 'Why it matters' gets its own paragraph (markdown would
    otherwise glue it onto the last bullet)."""
    st.markdown(
        re.sub(r"\n\s*Why it matters:", "\n\n**Why it matters:**", summary, flags=re.I)
    )


def _snippet(text: str | None, limit: int = 220) -> str:
    """One readable paragraph from a summary or article start (bullets become ' • ')."""
    text = re.sub(r"(^|\n)\s*[-*•]\s+", " • ", text or "")
    text = " ".join(text.split()).lstrip("• ").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _meta(r: dict) -> str:
    parts = [r.get("source_name"), r.get("category"), _date(r.get("published_at"))]
    if r.get("points") is not None:
        parts.append(f"▲ {r['points']}")
    if r.get("num_comments") is not None:
        parts.append(f"{r['num_comments']} comments")
    return " · ".join(p for p in parts if p)


def _health_caption(source_id: str) -> None:
    """One status line per source page. A failing source must show its error even if
    it has never succeeded (last_fetch_at only advances on success)."""
    row = next((h for h in run_db(db.source_health) if h["id"] == source_id), None)
    status = (row or {}).get("last_status") or ""
    last_ok = row["last_fetch_at"] if row else None
    if status.startswith("error"):
        ok_part = (
            f" Last success {last_ok:%b %d, %H:%M}."
            if last_ok
            else " It has never succeeded."
        )
        st.warning(f"Last fetch failed: {status}.{ok_part}")
    elif not last_ok:
        st.caption("Not fetched yet. Run: `uv run python -m digest run`")
    else:
        st.caption(
            f"Last fetch {last_ok:%b %d, %H:%M} · {status} · {row['total_items']} items saved"
        )


# --------------------------------------------------------------------------
# feed list
# --------------------------------------------------------------------------
def feed_view(
    page_key: str,
    title: str,
    source: dict | None = None,
    starred_only: bool = False,
    header_extra=None,
) -> None:
    """header_extra: optional callable that draws something under the title (list view only)."""
    ss = st.session_state
    
    # Track item changes and trigger scroll
    current_item = st.query_params.get("item")
    last_item = ss.get(f"last_item_{page_key}")
    if current_item != last_item:
        ss[f"last_item_{page_key}"] = current_item
        ss["_should_scroll_top"] = True
        ss["_scroll_key"] = ss.get("_scroll_key", 0) + 1
    
    # Render scroll target if needed
    scroll_to_top()
    
    # Check if item slug is in query params
    if st.query_params.get("item"):
        return item_detail(page_key, st.query_params.get("item"))
    
    open_key = f"open_{page_key}"
    if ss.get(open_key):
        return item_detail(page_key, ss[open_key])

    st.title(title)
    if header_extra:
        header_extra()
    if source:
        _health_caption(source["id"])

    query = st.text_input(
        "Search",
        key=f"q_{page_key}",
        label_visibility="collapsed",
        placeholder="Search by keyword or by meaning, e.g. 'cheaper model inference'",
    )
    category = source_id = None
    c1, c2, c3 = st.columns(3)
    date_label = c1.selectbox("Date", list(DATE_OPTIONS), key=f"date_{page_key}")
    if source:
        source_id = source["id"]
        default_sort = 1 if source.get("default_sort") == "points" else 0
        sort_label = c2.selectbox(
            "Sort (no search text)",
            list(SORT_OPTIONS),
            index=default_sort,
            key=f"sort_{page_key}",
        )
        starred = (
            True
            if starred_only
            else (c3.checkbox("Starred only", key=f"star_{page_key}") or None)
        )
    else:
        cat_label = c2.selectbox(
            "Category", ["All", *CATEGORIES], key=f"cat_{page_key}"
        )
        category = None if cat_label == "All" else cat_label
        names = {s["name"]: s["id"] for s in load_sources()}
        src_label = c3.selectbox("Source", ["All", *names], key=f"srcsel_{page_key}")
        source_id = names.get(src_label)
        d1, d2 = st.columns(2)
        sort_label = d1.selectbox(
            "Sort (no search text)", list(SORT_OPTIONS), key=f"sort_{page_key}"
        )
        starred = (
            True
            if starred_only
            else (d2.checkbox("Starred only", key=f"star_{page_key}") or None)
        )

    hours = DATE_OPTIONS[date_label]
    since = datetime.now(timezone.utc) - timedelta(hours=hours) if hours else None
    sort = SORT_OPTIONS[sort_label]

    # reset paging whenever a filter changes
    sig = (query, date_label, category, source_id, starred, sort)
    if ss.get(f"sig_{page_key}") != sig:
        ss[f"sig_{page_key}"] = sig
        ss[f"limit_{page_key}"] = PAGE_SIZE
    limit = ss[f"limit_{page_key}"]

    rows = run_db(
        search.search,
        query,
        source_id=source_id,
        category=category,
        since=since,
        starred=starred,
        sort=sort,
        limit=limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]

    if not rows:
        st.info(
            "No items match."
            if (query or starred or since or category or source_id)
            else "Nothing here yet. Run: `uv run python -m digest run`"
        )
        return
    st.caption(
        f"Showing {len(rows)} item(s)"
        + (" · ranked by relevance" if query.strip() else "")
    )

    for r in rows:
        with st.container(border=True):
            left, right = st.columns([9, 2])
            left.markdown(f"**{esc(r['title'])}**")
            left.caption(_meta(r))
            if r.get("snippet"):
                left.write(esc(_snippet(r["snippet"])))
            b1, b2 = right.columns(2)
            if b1.button("Open", key=f"o_{page_key}_{r['slug']}"):
                st.query_params["item"] = r["slug"]
                # Don't rerun - query_params change triggers auto-rerun
            if b2.button(
                "★" if r["starred"] else "☆",
                key=f"s_{page_key}_{r['id']}",
                help="Unstar" if r["starred"] else "Star",
            ):
                run_db(db.set_starred, r["id"], not r["starred"])
                st.rerun()

    if more and st.button(f"Load {PAGE_SIZE} more", key=f"more_{page_key}"):
        ss[f"limit_{page_key}"] = limit + PAGE_SIZE
        st.rerun()


# --------------------------------------------------------------------------
# item detail
# --------------------------------------------------------------------------
def item_detail(page_key: str, item_slug: str) -> None:
    ss = st.session_state
    item = run_db(db.get_item_by_slug, item_slug)

    if st.button("← Back to list", key=f"back_{page_key}"):
        st.query_params.clear()
        st.rerun()
    if not item:
        st.warning("That item no longer exists.")
        return

    st.header(item["title"])
    st.caption(_meta(item))
    c1, c2, c3 = st.columns([2, 2, 6])
    c1.link_button("Open original", item["url"])
    if item.get("hn_url"):
        c2.link_button("HN discussion", item["hn_url"])
    star_label = "★ Starred" if item["starred"] else "☆ Star"
    if c3.button(star_label, key=f"dstar_{page_key}_{item_slug}"):
        run_db(db.set_starred, item["id"], not item["starred"])
        st.rerun()

    st.subheader("Summary")
    if item["summary"]:
        render_summary(item["summary"])
    else:
        st.caption("No summary yet. Only items picked for a digest are summarized.")

    others = (
        [
            m
            for m in run_db(db.cluster_members, item["cluster_id"])
            if m["id"] != item["id"]
        ]
        if item["cluster_id"]
        else []
    )
    if others:
        st.subheader("Also covered by")
        for m in others:
            st.markdown(f"{esc(m['source_name'])}: [{esc(m['title'])}]({m['url']})")

    similar = run_db(db.similar_items, item["id"], 5)
    if similar:
        st.subheader("Similar items")
        for s in similar:
            col_a, col_b = st.columns([9, 1])
            col_a.write(f"{esc(s['title'])}  ({s['similarity']:.2f})")
            if col_b.button("Open", key=f"sim_{page_key}_{item['id']}_{s['id']}"):
                st.query_params["item"] = s["slug"]
                # query_params change triggers auto-rerun

    st.subheader("Full text")
    if item["content"]:
        for para in re.split(r"\n+", item["content"]):
            if para.strip():
                st.markdown(esc(para.strip()))
    else:
        st.caption("Full text was not available (page blocked or not extractable).")
