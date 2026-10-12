- **Shared global state:** `history` and `_pending` (the search query handoff) are module-level variables. With concurrent users, one person's chat history or search query can leak into another's. Load history per session from the database, and pass the query through a `contextvars.ContextVar` or NeMo's context instead of a global.
- **Async:** use `await rails.generate_async(...)` in your FastAPI route. The sync `generate` I used would block the event loop. Presidio and spaCy are also synchronous and CPU-bound, so wrap `mask_pii` in `asyncio.to_thread`.
- **Load once:** build `LLMRails`, the Presidio engines and the spaCy model once at startup (FastAPI lifespan), not per request. Check memory on your Render plan, since each worker loads its own copy.
- **Escape bot output:** LLM text can contain HTML, so never use `|safe` in your templates. If you render markdown, sanitize it (for example with `nh3`).
- **Abuse and cost control:** every message costs up to three LLM calls plus a Tavily credit. Add per-user and per-IP rate limits, a max message length, and a session or auth requirement. HTMX POSTs also need CSRF protection.

**Supabase**
- **Keys:** call the database only from the server with the service key, and never send that key to the browser.
- **Row-level security:** if users ever read their own chats directly, turn on RLS.
- **Privacy:** Presidio is best-effort. It missed the Reddit username and over-flags model names, so don't rely on it for compliance. Store the masked text, decide a retention period, and tell users chats are stored.
- **Logging:** log blocked messages and the guardrail verdicts in a table. That's how you'll find holes and false refusals.
- **Context size:** trim history to the last N turns so cost and latency don't grow.

**Behaviour and quality**
- **Regression tests:** an LLM-based classifier drifts when the model or prompt changes, and the Reddit false positive showed that. Keep a small test list of Meta evasions, off-topic questions and legitimate edge cases, and run it whenever you touch prompts or upgrade the model.
- **Separate model for the checks:** I used the same model for the classifier and the answers. Make the classifier a cheaper `CLASSIFIER_MODEL` setting. Keep the answer model strong.
- **Version pinning:** pin `nemoguardrails` and `presidio` in `uv.lock` and retest after upgrades.
- **Meta rule:** a "never mention Meta" rule means honest answers to broad questions like "best open-source models" can end in a refusal. That's fine for a demo but may feel odd on a public site. Decide on purpose whether that's acceptable.
- **Guardrails aren't a security boundary:** give the bot no database or tool access. Treat it as a text generator that can be tricked.

**UX with HTMX**
- A turn can take several seconds, so add `hx-indicator` and `hx-disable-elt` on the send button, and append messages with `hx-swap="beforeend"`.
- Skip streaming at first. Output checks need the full reply, so streaming means extra NeMo configuration.
- If OpenAI is down, the classifier fails closed and the bot refuses everything. Show a friendly "try again" message for that case.
