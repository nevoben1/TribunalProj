# AI Tribunal

Class project. Courtroom sim: 4 AI lawyers + 3 AI judges via OpenRouter. See [architecture.md](architecture.md) for layout, [specs.md](specs.md) for behavior contract.

## Stack
Backend: FastAPI (Python, async httpx), Mongo (motor). Frontend: Next.js, `EventSource` SSE.

## Flow
`POST /trials` (validate + create pending doc) → `GET /trials/{id}/stream` (SSE) runs 4 lawyers sequentially, 3 judges in parallel, persists to Mongo, emits `done`.

## Hard rules
- Charge sheet: reject <20 or >4000 chars, 422, before trial doc created.
- Judge output must be strict JSON `{verdict, reasoning}` (native JSON mode preferred). Never regex/guess a verdict from prose — parse fail = retry once, then `error` event.
- Every OpenRouter call: 30s timeout, 1 retry max, no retry loops.
- One failed agent (lawyer or judge) never aborts the trial — emit `error` event for that role, mark `status: "failed"` in Mongo, continue.
- Cap lawyer `max_tokens` (~250–400). Log `usage` per call.
- No prompt caching, no consensus/aggregation step, no auth.
- Models: user picks `model_mode` (same/distinct) per trial, no restart needed. same=all 7 use `SAME_MODEL`; distinct=per-participant `*_MODEL` env vars. Never hardcode model ids.

## Out of scope (don't build)
Rebuttals, multi-round debate, auth, ground-truth scoring, cloud deploy config.
