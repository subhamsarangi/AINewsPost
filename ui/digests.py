"""Page listing past digests, with a PDF download button for each."""

from pathlib import Path

import streamlit as st

from digest import db
from digest.config import ROOT
from views import run_db

MAX_DIGESTS = 14


@st.cache_data(show_spinner=False)
def _read_pdf(
    path: str, mtime: float
) -> bytes:  # mtime in the key: cache refreshes on rebuild
    return Path(path).read_bytes()


def digests_page() -> None:
    st.title("Digests")
    rows = run_db(db.list_digests, MAX_DIGESTS)
    if not rows:
        st.info("No digests yet. Run: `uv run python -m digest run`")
        return
    for d in rows:
        path = ROOT / d["pdf_path"]
        with st.container(border=True):
            left, right = st.columns([5, 2])
            left.markdown(f"**{d['date']:%A, %B %d, %Y}** · {d['n_items']} items")
            for it in run_db(db.digest_items, d["id"]):
                left.caption(f"{it['rank']}. {it['title']}")
            if path.exists():
                right.download_button(
                    "Download PDF",
                    _read_pdf(str(path), path.stat().st_mtime),
                    file_name=path.name,
                    mime="application/pdf",
                    key=f"dl_{d['id']}",
                )
            else:
                right.caption("PDF file is missing from disk.")
