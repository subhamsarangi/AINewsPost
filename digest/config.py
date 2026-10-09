"""Loads .env and sources.yaml; exposes settings and the source list."""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DIGEST_DIR = OUTPUT_DIR / "digests"
SOURCES_FILE = ROOT / "sources.yaml"

CATEGORIES = ["research", "mlops", "community", "funding"]
SOURCE_TYPES = {"rss", "hn", "scrape"}

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    database_url: str
    embed_model: str
    chat_model: str
    digest_max_items: int
    dedup_threshold: float
    hn_min_points: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key or key.startswith("sk-..."):
        log.warning("OPENAI_API_KEY is not set in .env")
    return Settings(
        openai_api_key=key,
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://digest:digest@localhost:5432/digest"
        ),
        embed_model=os.getenv("EMBED_MODEL", "text-embedding-3-small"),
        chat_model=os.getenv("CHAT_MODEL", "gpt-4o-mini"),
        digest_max_items=int(os.getenv("DIGEST_MAX_ITEMS", "5")),
        dedup_threshold=float(os.getenv("DEDUP_THRESHOLD", "0.88")),
        hn_min_points=int(os.getenv("HN_MIN_POINTS", "100")),
    )


def _validate(src: dict, seen: set[str]) -> None:
    for field in ("id", "name", "type"):
        if field not in src:
            raise ValueError(f"source missing '{field}': {src}")
    if src["id"] in seen:
        raise ValueError(f"duplicate source id: {src['id']}")
    if src["type"] not in SOURCE_TYPES:
        raise ValueError(f"{src['id']}: type must be one of {sorted(SOURCE_TYPES)}")
    cat = src.get("category")
    if cat is not None and cat not in CATEGORIES:
        raise ValueError(f"{src['id']}: category must be one of {CATEGORIES}")
    if src["type"] in ("rss", "scrape") and "url" not in src:
        raise ValueError(f"{src['id']}: '{src['type']}' source needs a url")
    seen.add(src["id"])


def load_sources(include_todo: bool = False) -> list[dict]:
    """Return sources from sources.yaml.

    Sources whose url is still 'TODO' are skipped (with a warning) unless
    include_todo=True, so a half-filled file never breaks a run.
    """
    with open(SOURCES_FILE, encoding="utf-8") as f:
        raw = (yaml.safe_load(f) or {}).get("sources", [])

    seen: set[str] = set()
    out: list[dict] = []
    for src in raw:
        _validate(src, seen)
        src.setdefault("category", None)
        src.setdefault("default_sort", "date")
        if not include_todo and str(src.get("url", "")).strip().upper() == "TODO":
            log.warning("source '%s' skipped: url is still TODO", src["id"])
            continue
        out.append(src)
    return out


def get_source(source_id: str) -> dict:
    for src in load_sources(include_todo=True):
        if src["id"] == source_id:
            return src
    raise KeyError(f"unknown source: {source_id}")
