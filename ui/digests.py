"""Daily picks page: the digest for a chosen day (latest by default).

Shows that day's picks with summaries, a PDF download, a cheap "Rebuild PDF"
(from the saved picks: no fetching, no OpenAI), a dropdown for older days, and
a "Generate today's digest" button when today has none (same as `python -m digest run`).
"""

from datetime import date

import streamlit as st

from digest import db, llm
import views
from views import run_db

MAX_DIGESTS = 60


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _fetch_pdf_from_r2(url: str) -> bytes:
    """Fetch PDF from R2 URL (cached by URL)."""
    import httpx
    try:
        return httpx.get(url, follow_redirects=True, timeout=30).raise_for_status().content
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            raise RuntimeError(
                "R2 bucket is private. Make it public in Cloudflare dashboard or set R2_PUBLIC_URL to a custom domain."
            ) from e
        raise


def _friendly(exc: Exception) -> str | None:
    """Same mapping as the CLI. None = a real bug (let it show)."""
    if isinstance(exc, db.DatabaseProblem):
        return str(exc)
    return llm.explain(exc) or (str(exc) if isinstance(exc, RuntimeError) else None)


def _flash(kind: str, msg: str) -> None:
    """Message that survives the st.rerun() that follows an action."""
    st.session_state["picks_flash"] = (kind, msg)


def _show_flash() -> None:
    kind, msg = st.session_state.pop("picks_flash", (None, None))
    if msg:
        {"success": st.success, "error": st.error}.get(kind, st.info)(msg)


def _label(d: dict, today: date) -> str:
    tag = " · today" if d["date"] == today else ""
    return f"{d['date']:%a, %b %d, %Y}{tag} · {d['n_items']} picks"


def _load_picks(conn, digest_id: int) -> list[dict]:
    items = []
    for row in db.digest_items(conn, digest_id):
        item = db.get_item(conn, row["id"])
        if item:
            item["rank"] = row["rank"]
            items.append(item)
    return items


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------
def _generate_today() -> None:
    from digest import pipeline  # heavy import: only when needed

    flash = None
    with st.spinner(
        "Fetching sources, ranking, summarizing and building the PDF. "
        "This takes a few minutes. Keep this tab open."
    ):
        try:
            result = pipeline.run()
        except Exception as e:
            msg = _friendly(e)
            if msg is None:
                raise
            flash = ("error", msg)
        else:
            failed = [s["id"] for s in result["sources"] if s["error"]]
            tail = (
                f" ({len(failed)} source(s) failed: {', '.join(failed)})"
                if failed
                else ""
            )
            if result.get("pdf") and not result.get("note"):
                flash = ("success", "Today's digest is ready." + tail)
            else:
                flash = ("info", (result.get("note") or "Done.") + tail)
    _flash(*flash)
    # jump to the newest digest: forget the choice and give the dropdown a fresh identity
    # (Streamlit keeps a keyed widget's value on the frontend, so popping its key is not enough)
    st.session_state.pop("picks_sel", None)
    st.session_state["picks_gen"] = st.session_state.get("picks_gen", 0) + 1
    st.rerun()


def _rebuild_pdf(d: dict) -> None:
    from digest import pdf, r2

    with st.spinner("Rebuilding the PDF from the saved picks..."):
        try:

            def build(conn):
                items = _load_picks(conn, d["id"])
                for it in items:
                    it["reason"] = ""  # the pick reason is not stored
                    it["also_covered"] = (
                        [
                            m
                            for m in db.cluster_members(conn, it["cluster_id"])
                            if m["id"] != it["id"]
                        ]
                        if it["cluster_id"]
                        else []
                    )
                return items

            items = run_db(build)
            pdf_url = pdf.render(d["date"], items)
            
            # Update digest row with new R2 URL
            with db.connect() as conn:
                db.save_digest(conn, d["date"], pdf_url, [i["id"] for i in items])
            
            _flash("success", f"PDF rebuilt for {d['date']:%b %d, %Y}.")
        except Exception as e:
            msg = _friendly(e)
            if msg is None:
                raise
            _flash("error", msg)
    st.rerun()


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------
def picks_page() -> None:
    ss = st.session_state
    
    # Track item changes and trigger scroll
    current_item = st.query_params.get("item")
    last_item = ss.get("last_item_picks")
    if current_item != last_item:
        ss["last_item_picks"] = current_item
        ss["_should_scroll_top"] = True
        ss["_scroll_key"] = ss.get("_scroll_key", 0) + 1
    
    # Render scroll target if needed
    views.scroll_to_top()
    
    if st.query_params.get("item"):
        return views.item_detail("picks", st.query_params.get("item"))

    st.title("Daily picks")
    _show_flash()
    digests = run_db(db.list_digests, MAX_DIGESTS)
    today = date.today()

    if not digests or digests[0]["date"] != today:
        with st.container(border=True):
            st.markdown(
                "**No digest for today yet.**" if digests else "**No digests yet.**"
            )
            st.caption(
                "Fetches all sources, picks the best items, summarizes them and builds "
                "the PDF. Takes a few minutes and costs a few cents of OpenAI credit. "
                "Same as running `uv run python -m digest run`."
            )
            if st.button("Generate today's digest", type="primary", key="gen_today"):
                _generate_today()
    if not digests:
        return

    # The selectbox's own state is dropped while the detail view is open, so the choice
    # is also kept in a plain session key and restored through `index`.
    ids = [d["id"] for d in digests]
    current = ss.get("picks_sel") if ss.get("picks_sel") in ids else ids[0]
    chosen = st.selectbox(
        "Day",
        ids,
        index=ids.index(current),
        key=f"picks_day_{ss.get('picks_gen', 0)}",
        format_func={d["id"]: _label(d, today) for d in digests}.get,
    )
    ss["picks_sel"] = chosen
    d = next(x for x in digests if x["id"] == chosen)

    left, mid, right = st.columns([5, 2, 2])
    left.subheader(f"{d['date']:%A, %B %d, %Y}")
    
    # d["pdf_path"] is now an R2 URL
    if d["pdf_path"].startswith("https://"):
        try:
            pdf_bytes = _fetch_pdf_from_r2(d["pdf_path"])
            mid.download_button(
                "Download PDF",
                pdf_bytes,
                file_name=f"{d['date'].isoformat()}.pdf",
                mime="application/pdf",
                key=f"dl_{d['id']}",
            )
        except RuntimeError:
            mid.caption("❌ PDF unavailable (bucket private)")
    else:
        mid.caption("No PDF URL.")
    if right.button(
        "Rebuild PDF",
        key=f"rb_{d['id']}",
        help="Re-create the PDF from the saved picks. No fetching, no OpenAI cost.",
    ):
        _rebuild_pdf(d)

    items = run_db(_load_picks, d["id"])
    if not items:
        st.info("This digest has no items.")
    for it in items:
        with st.container(border=True):
            body, btns = st.columns([9, 2])
            body.markdown(f"**{it['rank']}. {views.esc(it['title'])}**")
            body.caption(views._meta(it))
            if it["summary"]:
                with body:
                    views.render_summary(it["summary"])
            else:
                body.caption("No summary saved for this item.")
            if btns.button("Details", key=f"pd_{d['id']}_{it['id']}"):
                st.query_params["item"] = it["slug"]
                # query_params change triggers auto-rerun
            btns.link_button("Original", it["url"])
