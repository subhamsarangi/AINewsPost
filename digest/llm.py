"""The only file that imports openai: embed(), pick_top(), summarize()."""

import json
import logging
import re

import openai
from openai import OpenAI

from .config import get_settings

log = logging.getLogger(__name__)

EMBED_BATCH = 100
MAX_EMBED_CHARS = 6000
MAX_SUMMARY_CHARS = 12000

_client: OpenAI | None = None
_usage = {"calls": 0, "embed_tokens": 0, "chat_in": 0, "chat_out": 0}


def client() -> OpenAI:
    global _client
    if _client is None:
        key = get_settings().openai_api_key
        if not key or key.startswith("sk-..."):
            raise RuntimeError("OPENAI_API_KEY missing. Set it in .env")
        _client = OpenAI(api_key=key, max_retries=5, timeout=60)
    return _client


def usage_report() -> str:
    u = _usage
    return (
        f"openai: {u['calls']} calls, {u['embed_tokens']} embed tokens, "
        f"{u['chat_in']} chat in, {u['chat_out']} chat out"
    )


def explain(exc: Exception) -> str | None:
    """Friendly message for an OpenAI API error, or None if exc is not one.
    Entry points use this so the CLI never imports openai itself."""
    if isinstance(exc, openai.AuthenticationError):
        return "OpenAI rejected the API key. Check OPENAI_API_KEY in .env."
    if isinstance(exc, openai.NotFoundError):
        return (
            "OpenAI says a model was not found. Check CHAT_MODEL and EMBED_MODEL in .env "
            "against the models your account can use."
        )
    if isinstance(exc, openai.RateLimitError):
        return (
            "OpenAI rate limit or quota exceeded. Check billing and usage limits at "
            "platform.openai.com. Progress is saved; rerun later."
        )
    if isinstance(exc, openai.APIConnectionError):
        return "Cannot reach OpenAI (network down or blocked?). Progress is saved; rerun later."
    if isinstance(exc, openai.APIStatusError):
        return f"OpenAI API error {exc.status_code}. Progress is saved; rerun later."
    return None


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------
def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts in batches. Output order matches input order."""
    model = get_settings().embed_model
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        # API rejects empty strings, so substitute a space
        batch = [
            (t or "").strip()[:MAX_EMBED_CHARS] or " "
            for t in texts[i : i + EMBED_BATCH]
        ]
        resp = client().embeddings.create(model=model, input=batch)
        _usage["calls"] += 1
        _usage["embed_tokens"] += resp.usage.total_tokens
        out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return out


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


# --------------------------------------------------------------------------
# Chat helper
# --------------------------------------------------------------------------
def _chat(system: str, user: str, json_mode: bool = False) -> str:
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = client().chat.completions.create(
        model=get_settings().chat_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **kwargs,
    )
    _usage["calls"] += 1
    if resp.usage:
        _usage["chat_in"] += resp.usage.prompt_tokens
        _usage["chat_out"] += resp.usage.completion_tokens
    return (resp.choices[0].message.content or "").strip()


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    return json.loads(raw)


# --------------------------------------------------------------------------
# Ranking: one call picks up to N items
# --------------------------------------------------------------------------
PICK_SYSTEM = """You curate a daily AI news digest for one reader.
Reader interests: {interest}

From the numbered candidates, choose AT MOST {n} items worth reading today.
Rules:
- Quality over quantity. Return fewer than {n} (even 0) if the day is thin.
- Prefer substance: new research, real engineering lessons, notable launches,
  insightful opinion, meaningful funding news. Skip fluff, hype, and rehashes.
- Aim for variety across categories (research, mlops, news, community, funding)
  when quality allows. Do not force a category that has nothing good.
- Do not pick two items about the same story.

Reply with JSON only:
{{"picks": [{{"id": <candidate id>, "reason": "<max 15 words>"}}]}}
Order picks best first."""


def pick_top(candidates: list[dict], interest: str, max_items: int = 5) -> list[dict]:
    """candidates: dicts from db.rank_candidates. Returns [{'id', 'reason'}, ...].

    [] means the model found nothing worth reading. Unparseable output raises ValueError.
    """
    if not candidates:
        return []
    lines = []
    for c in candidates:
        tag = c.get("category") or "?"
        pts = f", {c['points']} pts" if c.get("points") else ""
        snippet = " ".join((c.get("snippet") or "").split())[:300]
        lines.append(
            f"[{c['id']}] ({c['source_id']}/{tag}{pts}) {c['title']} :: {snippet}"
        )

    raw = _chat(
        PICK_SYSTEM.format(interest=interest, n=max_items),
        "Candidates:\n" + "\n".join(lines),
        json_mode=True,
    )
    try:
        picks = _parse_json(raw).get("picks", [])
        if not isinstance(picks, list):
            raise TypeError("'picks' is not a list")
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        # raise (not []) so the caller can tell "bad output" from "nothing worth reading"
        raise ValueError(f"pick_top: bad model output: {raw[:200]!r}") from e

    valid = {c["id"] for c in candidates}
    result: list[dict] = []
    for p in picks:
        pid, reason = (
            (p.get("id"), p.get("reason", "")) if isinstance(p, dict) else (p, "")
        )
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if pid in valid and all(pid != r["id"] for r in result):
            result.append({"id": pid, "reason": reason})
    return result[:max_items]


# --------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------
SUMMARY_SYSTEM = """You write summaries for a busy, technical reader.
Format exactly:
- 3 to 5 bullet points (each starts with "- "), concrete facts, numbers, names.
- Then one final line starting with "Why it matters: " (one sentence).
If discussion comments are provided, add one bullet starting
"- Community: " capturing the main reactions or disagreement.
No intro, no preamble, no markdown headers. Never invent facts not in the text."""


def summarize(title: str, content: str, comments: list[str] | None = None) -> str:
    body = (content or "").strip()[:MAX_SUMMARY_CHARS]
    if not body:
        body = "(full text unavailable; summarize from the title only and say so)"
    user = f"Title: {title}\n\nText:\n{body}"
    if comments:
        joined = "\n---\n".join(c.strip()[:800] for c in comments[:3])
        user += f"\n\nTop discussion comments:\n{joined}"
    return _chat(SUMMARY_SYSTEM, user)
