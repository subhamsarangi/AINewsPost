"""CLI entry point: `python -m digest run` (more subcommands are LATER TODO).

    uv run python -m digest run              daily run: fetch, rank, summarize, PDF
    uv run python -m digest run --dry-run    stop after ranking (no summaries, no PDF)
    uv run python -m digest run --no-fetch   skip fetching, work with what is in the DB
    uv run python -m digest run --force      rebuild today's digest

Set DIGEST_DEBUG=1 to see full tracebacks instead of friendly messages.
"""

import argparse
import os
import sys

from . import db, llm
from .config import ROOT


def cmd_run(args: argparse.Namespace) -> int:
    from . import pipeline  # imported late: keeps --help instant

    result = pipeline.run(
        dry_run=args.dry_run, no_fetch=args.no_fetch, force=args.force
    )

    failed = [s for s in result["sources"] if s["error"]]
    ok = len(result["sources"]) - len(failed)
    if result["sources"]:
        new = sum(s["new"] for s in result["sources"])
        print(f"\nSources: {ok} ok, {len(failed)} failed, {new} new items")
        for s in failed:
            print(f"  FAILED {s['id']}: {s['error']}")
    if result["picks"]:
        print("\nPicks:" if not args.dry_run else "\nPicks (dry run):")
        for n, p in enumerate(result["picks"], start=1):
            print(f"  {n}. {p['title'][:90]}\n     why: {p['reason']}")
    if result["pdf"]:
        print(f"\nDigest: {ROOT / result['pdf']}")
    if result["note"]:
        print(f"\n{result['note']}")
    return 0


# ---- LATER TODO: stubs. Registered so --help shows the plan; not implemented. ----
def _later(name: str, what: str) -> int:
    print(f"'{name}' is not implemented yet (LATER TODO): {what}", file=sys.stderr)
    return 2


def cmd_ui(args: argparse.Namespace) -> int:
    """LATER TODO: launch Streamlit via `sys.executable -m streamlit run ui/app.py`."""
    return _later("ui", "launch the Streamlit UI")


def cmd_search(args: argparse.Namespace) -> int:
    """LATER TODO: print top results of search.search(conn, ' '.join(args.query))."""
    return _later("search", "search saved items from the terminal")


def cmd_health(args: argparse.Namespace) -> int:
    """LATER TODO: print db.source_health(conn) as a table."""
    return _later("health", "show per-source fetch health")


COMMANDS = {"run": cmd_run, "ui": cmd_ui, "search": cmd_search, "health": cmd_health}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m digest", description="Personal AI news digest."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run the daily pipeline")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="stop after ranking: no summaries, no PDF, nothing saved",
    )
    run.add_argument("--no-fetch", action="store_true", help="skip fetching sources")
    run.add_argument(
        "--force", action="store_true", help="rebuild today's digest even if one exists"
    )

    sub.add_parser("ui", help="[LATER TODO] launch the Streamlit UI")
    sub.add_parser("search", help="[LATER TODO] search saved items").add_argument(
        "query", nargs="+"
    )
    sub.add_parser("health", help="[LATER TODO] per-source fetch health")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles: never crash on emoji
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.cmd](args)
    except KeyboardInterrupt:
        print(
            "\nInterrupted. Everything already finished is saved; rerun to resume.",
            file=sys.stderr,
        )
        return 130
    except Exception as e:
        if os.getenv("DIGEST_DEBUG"):
            raise
        if isinstance(e, db.DatabaseProblem):
            msg = str(e)
        elif api_msg := llm.explain(e):
            msg = api_msg
        elif isinstance(e, RuntimeError):  # our own friendly errors (PDF, API key, ...)
            msg = str(e)
        else:
            raise  # a real bug: show the traceback
        print(f"\nerror: {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
