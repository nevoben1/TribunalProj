# AI Tribunal — Specifications

Class project. Web app simulates courtroom trial via AI agents over OpenRouter. Architecture ref: [architecture.md](architecture.md).

## Success Criteria

Primary: each of 3 judges produces a verdict (`guilty` | `not_guilty`) with reasoning text, for any valid charge sheet submission. Trial completes and persists even if some agent calls fail.

## Functional Requirements

### Charge sheet input
- Free text, no required structure/fields (no forced "question" field).
- **Min length**: 20 chars. Reject below with 422 validation error, no trial created.
- **Max length**: 4000 chars (~1000 tokens). Reject above with 422. Prevents runaway prompt/token cost; enforced at API layer before any model call.
- Validation happens synchronously on `POST /trials`, before trial doc is created.

### Trial flow
1. `POST /trials {charge_sheet}` → validates length → creates trial doc (status `pending`) → returns `{id}`.
2. `GET /trials/{id}/stream` (SSE, `EventSource`) → triggers orchestrator on first connection:
   - Run 4 lawyer speeches sequentially: prosecutor_1, prosecutor_2, defender_1, defender_2. Yield `speech` event after each.
   - Run 3 judges in parallel (`asyncio.gather`), each receives charge sheet + all 4 speeches. Yield `verdict` event as each resolves.
   - Persist full trial doc to Mongo.
   - Yield `done` event with trial id.
3. `GET /trials` — paginated list (charge sheet excerpt + verdict summary) for history page.
4. `GET /trials/{id}` — full non-streaming replay of completed trial.

### Judge verdict — structured output (pitfall: judge returns prose)
- Judges prompted to return **strict JSON**: `{"verdict": "guilty"|"not_guilty", "reasoning": "..."}`.
- Prefer OpenRouter/model native JSON mode (`response_format: {type: "json_object"}`) where model supports it; else JSON-instructed prompt.
- Parse response as JSON. On parse failure:
  - Retry once (same call, same prompt).
  - If retry also fails to parse: treat as agent failure — see error handling below. Do **not** attempt regex/keyword salvage from prose; a bad parse produces an explicit `error` event, not a guessed verdict.
- Validate parsed `verdict` is exactly one of the two allowed enum values (case-insensitive normalize); anything else = parse failure, same handling as above.

### Model call handling (pitfall: timeout)
- `agents/base.py` httpx client: **timeout = 30s** per call.
- On timeout or non-2xx from OpenRouter: **1 retry**, same request.
- If retry also fails (timeout, error, or judge JSON parse failure): catch, yield `error` SSE event for that role:
  `{"type": "error", "role": "<role>", "message": "<short fallback reason>"}`.
- Trial continues — a single failed lawyer speech or judge verdict does not abort the run. Failed role is recorded in the Mongo doc with `status: "failed"` and no `content`/`verdict` field, rather than being silently omitted, so history/replay shows what happened.
- Success criterion nuance: trial still "succeeds" overall if at least 1 judge returns a valid verdict; full success is 3/3 judges verdict. Surfaced to user via UI (see below) rather than blocking.
- **Pitfall: hidden reasoning tokens.** Some free-tier models are reasoning-capable and, unless told otherwise, silently spend part or all of `max_tokens` on an internal reasoning phase before emitting visible content — observed producing fully empty `content` on real free-tier calls. Every OpenRouter call sends `reasoning: {enabled: false}` to force the full token budget into visible output. A 200 response with empty/falsy `content` is treated the same as a call failure (counts toward the single retry, then `status: "failed"`) rather than being surfaced as a blank "ok" entry.

### Model configuration (same vs distinct)

- Per-trial toggle: user picks `model_mode: "same" | "distinct"` on the submission form, sent with `POST /trials`. No server restart needed to switch — both model pools are always configured server-side.
- `same`: all 7 participants (4 lawyers + 3 judges) use `SAME_MODEL`.
- `distinct`: each of the 7 participants uses its own env-configured model (`PROSECUTOR_1_MODEL` ... `JUDGE_3_MODEL`).
- Resolved per-call via `settings.model_for_role(role, model_mode)`; trial doc records the `model_mode` used for traceability. Two trials submitted back to back can use different modes.

### Token & cost controls
- `max_tokens` cap on lawyer speech calls (~250–400 tokens).
- Cheap/free models for lawyers; stronger model reserved for judges.
- Log `usage` (prompt/completion tokens) per speech/verdict entry, from OpenRouter response.
- No retry loops beyond the single retry above.
- No prompt caching.

## Mongo Document Shape

```json
{
  "_id": ObjectId,
  "charge_sheet": "text",
  "created_at": ISODate,
  "status": "pending|running|completed",
  "speeches": [
    {"role": "prosecutor_1", "persona": "...", "model": "...", "status": "ok|failed", "content": "...", "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
  ],
  "verdicts": [
    {"role": "judge_1", "persona": "...", "model": "...", "status": "ok|failed", "verdict": "guilty|not_guilty", "reasoning": "...", "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
  ]
}
```

## API Surface

| Method | Path | Notes |
|---|---|---|
| POST | `/trials` | body `{charge_sheet, model_mode}`, charge_sheet 20–4000 chars, model_mode "same"\|"distinct" (default "same"); returns `{id}` |
| GET | `/trials/{id}/stream` | SSE, triggers orchestration on first connect |
| GET | `/trials` | paginated list |
| GET | `/trials/{id}` | full trial doc, non-streaming |

## SSE Event Types

- `speech` — `{role, content, usage}`
- `verdict` — `{role, verdict, reasoning, usage}`
- `error` — `{role, message}` (role's call failed after retry)
- `done` — `{trial_id}`

## Frontend Requirements

- Submission form: client-side length hint (20–4000 chars) mirroring backend validation, shows inline error on 422. Includes a same/distinct model toggle, sent as `model_mode` with the trial.
- Trial page: 4 speech cards + 3 verdict cards, pending state until each event lands; failed roles show an error state (not blank/hung).
- History page: excerpt + 3-verdict summary, link to replay (fetches completed doc, no streaming).

## Explicitly Out of Scope

- Rebuttal / multi-round debate
- Auth / multi-user
- Ground-truth verdict / accuracy scoring
- Cloud deploy config
- Judge consensus/aggregation step

## Verification Checklist

- `POST /trials` with charge sheet <20 chars → 422, no doc created.
- `POST /trials` with charge sheet >4000 chars → 422, no doc created.
- Valid charge sheet → 4 speech events, then 3 verdict events, then done, in order.
- Bad model id (simulated failure) → `error` event for that role, trial still completes with `done`.
- Judge forced to return prose (bad model or prompt) → parse fails, retries once, then `error` event — verdict is never fabricated from partial prose.
- Mongo doc after run: `speeches`/`verdicts` arrays reflect `ok`/`failed` status accurately; `/history` and replay show the same.
