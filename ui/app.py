"""Streamlit entry: builds the sidebar from sources.yaml.

Run from the project root:  uv run streamlit run ui/app.py
Pages: All items (home), Daily picks, Starred, then one page per source grouped by category.
Adding a source to sources.yaml adds its page automatically.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `import digest` works under streamlit

import streamlit as st  # noqa: E402

st.set_page_config(page_title="AI Digest", page_icon="📰", layout="wide")

import digests  # noqa: E402  (ui/digests.py)
import views  # noqa: E402  (ui/views.py)
from digest import db  # noqa: E402
from digest.config import CATEGORIES, load_sources  # noqa: E402

# Fail with a readable message (not a stack trace) if the database is not usable.
if not st.session_state.get("db_ok"):
    try:
        db.check()
        st.session_state["db_ok"] = True
    except db.DatabaseProblem as e:
        st.error(str(e))
        st.caption("Fix the problem above, then reload this page.")
        st.stop()


def _picks_link() -> None:
    """Shown at the top of the home page."""
    st.page_link(
        PICKS_PAGE, label="Daily picks: today's top items, past days, PDF", icon="📰"
    )
    latest = views.run_db(db.list_digests, 1)
    if latest:
        st.caption(
            f"Latest digest: {latest[0]['date']:%A, %B %d, %Y} · {latest[0]['n_items']} picks"
        )
    else:
        st.caption("No digest yet. Open Daily picks to generate one.")


def _all_page():
    views.feed_view("all", "All items", header_extra=_picks_link)


def _starred_page():
    views.feed_view("starred", "Starred", starred_only=True)


def _source_page(src: dict):
    def page():
        views.feed_view(f"src_{src['id']}", src["name"], source=src)

    return st.Page(page, title=src["name"], url_path=src["id"])


CATEGORY_LABELS = {
    "research": "Research",
    "mlops": "MLOps",
    "news": "News",
    "community": "Community",
    "funding": "Funding",
    "other": "Other",
}

PICKS_PAGE = st.Page(
    digests.picks_page, title="Daily picks", url_path="picks", icon="📰"
)

sections: dict[str, list] = {
    "Overview": [
        st.Page(_all_page, title="All items", url_path="all", default=True),
        PICKS_PAGE,
        st.Page(_starred_page, title="Starred", url_path="starred"),
    ]
}
by_category: dict[str, list] = {}
for src in load_sources():
    by_category.setdefault(src.get("category") or "other", []).append(_source_page(src))
for cat in [*CATEGORIES, "other"]:
    if cat in by_category:
        sections[CATEGORY_LABELS[cat]] = by_category[cat]

st.navigation(sections).run()
