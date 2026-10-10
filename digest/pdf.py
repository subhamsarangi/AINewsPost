"""Render the daily digest to PDF (Jinja2 + Playwright Chromium).

render(digest_date, items, out_path) -> Path   is what pipeline.py calls.
render_html(digest_date, items) -> str          same layout as HTML (open it in a
                                                browser to tweak the template, no Chromium needed).
Preview with real DB items:  uv run python -m digest.pdf
"""

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

FOOTER = (
    '<div style="width:100%;font-size:8px;color:#888;text-align:center;'
    'font-family:Arial,sans-serif;">AI Digest &middot; page '
    '<span class="pageNumber"></span> of <span class="totalPages"></span></div>'
)


# --------------------------------------------------------------------------
# Item dict -> template view
# --------------------------------------------------------------------------
def _fmt_date(d: datetime | None) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ") if d else ""


def _parse_summary(summary: str | None) -> dict:
    """llm.summarize output: '- ' bullets, a 'Why it matters:' line, maybe stray lines."""
    out = {"bullets": [], "why": None, "paras": []}
    for line in (summary or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("why it matters:"):
            out["why"] = line.split(":", 1)[1].strip()
        elif line[:2] in ("- ", "* ", "• "):
            out["bullets"].append(line[2:].strip())
        elif line.startswith(("-", "*", "•")) and len(line) > 1:
            out["bullets"].append(line[1:].strip())
        else:
            out["paras"].append(line)
    return out


def _view(number: int, item: dict) -> dict:
    s = _parse_summary(item.get("summary"))
    hn_line = ""
    if item.get("points") is not None:
        hn_line = f"{item['points']} points"
        if item.get("num_comments") is not None:
            hn_line += f", {item['num_comments']} comments"
    paras = [
        p.strip() for p in re.split(r"\n+", item.get("content") or "") if p.strip()
    ]
    return {
        "number": number,
        "title": item["title"],
        "url": item["url"],
        "source_name": item.get("source_name") or item.get("source_id", ""),
        "category": item.get("category"),
        "date_str": _fmt_date(item.get("published_at")),
        "hn_line": hn_line,
        "hn_url": item.get("hn_url"),
        "reason": (item.get("reason") or "").strip(),
        "also_covered": item.get("also_covered") or [],
        "bullets": s["bullets"],
        "why": s["why"],
        "paras": s["paras"],
        "text_paras": paras,
    }


def render_html(digest_date: date, items: list[dict]) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"])
    )
    return env.get_template("digest.html").render(
        date_long=digest_date.strftime("%A, %B %d, %Y").replace(" 0", " "),
        items=[_view(n, it) for n, it in enumerate(items, start=1)],
    )


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def render(digest_date: date, items: list[dict], out_path: Path) -> Path:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")  # never leave a half-written PDF
    html = render_html(digest_date, items)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                page.pdf(
                    path=str(tmp),
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=FOOTER,
                    margin={
                        "top": "18mm",
                        "bottom": "20mm",
                        "left": "18mm",
                        "right": "18mm",
                    },
                )
            finally:
                browser.close()
    except PlaywrightError as e:
        tmp.unlink(missing_ok=True)
        if "playwright install" in str(e) or "Executable doesn't exist" in str(e):
            raise RuntimeError(
                "Chromium for PDF output is not installed. "
                "Run: uv run playwright install chromium"
            ) from e
        raise

    try:
        os.replace(tmp, out_path)
    except PermissionError as e:  # Windows: PDF is open in a viewer
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Cannot overwrite {out_path}: close it in your PDF viewer " "and rerun."
        ) from e
    log.info("PDF written: %s (%d items)", out_path, len(items))
    return out_path


# --------------------------------------------------------------------------
# Preview with real items from the DB (no LLM calls, nothing saved)
# --------------------------------------------------------------------------
def _preview(n: int = 3) -> Path:
    from . import db
    from .config import OUTPUT_DIR

    with db.connect() as conn:
        rows = db.list_items(conn, limit=n)
        items = []
        for r in rows:
            full = db.get_item(conn, r["id"])
            full["reason"] = "preview run, not a real pick"
            full["also_covered"] = [
                m
                for m in db.cluster_members(conn, full["cluster_id"] or full["id"])
                if m["id"] != full["id"]
            ]
            items.append(full)
    return render(date.today(), items, OUTPUT_DIR / "preview.pdf")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    from . import db

    try:
        print(f"Wrote {_preview()}")
    except (db.DatabaseProblem, RuntimeError) as e:
        raise SystemExit(f"error: {e}")
