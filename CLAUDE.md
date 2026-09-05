# AI Tribunal

Class project. Courtroom sim: 4 AI lawyers + 3 AI judges via OpenRouter. See [architecture.md](architecture.md) for layout, [specs.md](specs.md) for behavior contract.

## Stack
Backend: FastAPI (Python, async httpx), Mongo (motor). Frontend: Next.js, `EventSource` SSE.

## Flow
`POST /trials` (validate + create pending doc) → `GET /trials/{id}/stream` (SSE) runs 4 lawyers sequentially, 3 judges in parallel, persists to Mongo, emits `done`.

## Hard rules
- Charge sheet: reject <20 or >4000 chars, 422, before trial doc created.
- Judge output must be strict JSON `{verdict, reasoning}` (native JSON mode preferred). Never regex/guess a verdict from prose — parse fail costs an attempt from the shared budget below, then `error` event.
- Every OpenRouter call: 30s timeout. **3 attempts (2 retries) per participant, shared across HTTP and parse failures** — no retry loops, ≤21 model calls per trial. Retry only transient classes (timeout, network, 429, 5xx, empty content, unparseable verdict); fail fast on auth/402/404/400.
- Backoff between attempts: `Retry-After` if present, else exponential 1s→8s. Never instant-retry.
- Every retry emits a `retry` SSE event (`role, retry, max_retries, reason`). Every final failure emits `error` with a **plain-language** `message` — never a raw status code, exception, or provider payload; raw detail to logs only.
- Mongo calls go through the retry helper in `db.py` (3 attempts, transient driver errors only). Final trial persist is the protected path; if it fails, emit `system` error and still emit `done`. `run_trial` never dies silently — stream always terminates with `done`.
- One failed agent (lawyer or judge) never aborts the trial — emit `error` event for that role, mark `status: "failed"` + `error_reason`/`error_code` in Mongo, continue.
- Cap `max_tokens` on every call via `AGENT_MAX_TOKENS` — judges included, or a provider's own default cap truncates the verdict JSON. Log `usage` per call.
- No prompt caching, no auth.
- Final verdict = deterministic majority tally over the judges that ruled (`tally_final_verdict`), **never an extra model call**. Failed judges are excluded, not counted as acquittals; a tie goes to the defendant; zero verdicts = no verdict. Stored on the trial doc, emitted as a `final_verdict` SSE event, recomputed on read for docs written before the field existed.
- Models: user picks `model_mode` (same/distinct) per trial, no restart needed. same=all 7 use `SAME_MODEL`; distinct=per-participant `*_MODEL` env vars. Never hardcode model ids.

## Out of scope (don't build)
Rebuttals, multi-round debate, auth, ground-truth scoring, cloud deploy config.
