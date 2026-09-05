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
  - Retry (same call, same prompt), drawing from the participant's shared 3-attempt budget below — parse retries and HTTP retries come out of the same pocket.
  - If the budget is exhausted and still nothing parses: treat as agent failure — see error handling below. Do **not** attempt regex/keyword salvage from prose; a bad parse produces an explicit `error` event, not a guessed verdict.
- Validate parsed `verdict` is exactly one of the two allowed enum values (case-insensitive normalize); anything else = parse failure, same handling as above.

### Model call handling (pitfall: timeout)
- `agents/base.py` httpx client: **timeout = 30s** per call.
- **Attempt budget is per participant, not per layer**: **3 attempts total (2 retries)** for every one of the 7 participants, covering HTTP failures *and* judge JSON parse failures alike. A judge that gets a 500 on attempt 1 and unparseable prose on attempt 2 has one attempt left — the two layers never multiply into 6 calls.
- **Failures are classified before retrying.** Only transient failures are retried; a permanent failure fails fast and does not burn the remaining retries:

  | Class | Examples | Retried |
  |---|---|---|
  | `timeout` | httpx read/connect timeout | yes |
  | `network` | DNS, connection reset, TLS | yes |
  | `rate_limit` | HTTP 429 | yes, honoring `Retry-After` when present |
  | `provider_error` | HTTP 5xx | yes |
  | `empty_content` | 200 with empty `content` | yes |
  | `malformed_response` | body is not the expected JSON envelope | yes |
  | `invalid_verdict` | judge JSON missing/!enum `verdict`, or non-string `reasoning` | yes |
  | `auth` | HTTP 401/403 | **no** |
  | `payment` | HTTP 402 | **no** |
  | `model_unavailable` | HTTP 404 | **no** |
  | `bad_request` | HTTP 400/422 | **no** |

- **Backoff between attempts**: `Retry-After` header when the provider sends one, otherwise exponential from `RETRY_BASE_DELAY_SECONDS` (default 1s), capped at `RETRY_MAX_DELAY_SECONDS` (default 8s). No instant-fire retries — an immediate repeat of a 429 is guaranteed to fail again.
- **The user is told a retry is happening.** Before each retry the orchestrator yields a `retry` SSE event for that role: `{"type": "retry", "role", "retry", "max_retries", "reason"}` — e.g. retry 1 of 2, reason "the model provider is rate-limiting our requests". The UI shows the role as *retrying (1/2)* rather than sitting on a silent "pending".
- If the last attempt also fails: yield `error` SSE event for that role — `{"type": "error", "role", "message", "reason_code"}`. `message` is a **plain-language explanation written for the end user** ("The model did not answer within the 30-second limit."), never the raw provider payload or an HTTP status line; raw detail goes to the server log only. `reason_code` is the class from the table above, for the UI and for debugging.
- Trial continues — a single failed lawyer speech or judge verdict does not abort the run. Failed role is recorded in the Mongo doc with `status: "failed"`, no `content`/`verdict`, plus `error_reason` (the user-facing message), `error_code`, and `attempts` used, rather than being silently omitted, so history/replay shows what happened and why.
- Success criterion nuance: trial still "succeeds" overall if at least 1 judge returns a valid verdict; full success is 3/3 judges verdict. Surfaced to user via UI (see below) rather than blocking.
- **Pitfall: hidden reasoning tokens.** Some free-tier models are reasoning-capable and, unless told otherwise, silently spend part or all of `max_tokens` on an internal reasoning phase before emitting visible content — observed producing fully empty `content` on real free-tier calls. Every OpenRouter call sends `reasoning: {effort: "low"}` (a plain disable is rejected by models that require reasoning) to push the token budget into visible output. A 200 response with empty/falsy `content` is treated as an `empty_content` failure — it consumes an attempt, and after the last attempt yields `error` — rather than being surfaced as a blank "ok" entry.

### Database call handling (pitfall: Mongo write fails after tokens are already spent)
- Motor client is built with `serverSelectionTimeoutMS` (default 5000) so a dead/unreachable Mongo fails in seconds instead of hanging the request for the driver's 30s default.
- Every Mongo operation goes through a shared retry helper: **3 attempts**, exponential backoff, retrying only transient driver errors (`ConnectionFailure` and its subclasses, `NetworkTimeout`, `ExecutionTimeout`, `WriteConcernError`). Permanent errors (bad query, auth failure) fail immediately.
- **The final trial persist is the protected path.** By the time it runs, all 7 model calls have been paid for and streamed to the user; losing it is the worst outcome in the system. It is retried per the helper, and if it still fails the orchestrator yields `{"type": "error", "role": "system", "message": "...", "reason_code": "persist_failed"}` and then still yields `done`, so the client keeps the results it already received on screen instead of hanging forever on an open stream.
- The `status: "running"` marker write is best-effort: failure is logged and the trial proceeds, because a status flag is not worth discarding a trial over.
- **The SSE generator never dies silently.** `run_trial` is wrapped end to end; any unexpected exception yields a `system` `error` event followed by `done` instead of tearing down the stream mid-flight with no explanation. The stream always terminates with `done`.
- Read/create routes (`POST /trials`, the two `GET`s) use the same helper; if Mongo is still unreachable after 3 attempts they return **503** with a plain-language detail, not an unhandled 500.

### Final verdict (majority of the bench)

A trial's final verdict is a **deterministic tally of the verdicts already returned** — arithmetic over data in hand, never an extra model call and never another agent.

- Only judges with `status: "ok"` vote. A failed judge is **excluded from the tally**, not silently counted as an acquittal.
- `guilty > not_guilty` → `guilty`. Otherwise → `not_guilty`.
- **A tie goes to the defendant** (1–1 with one judge failed → `not_guilty`), mirroring a bench with no majority to convict. Flagged as `tie_break: true` so the UI can say so rather than implying the bench chose acquittal.
- **A lone surviving judge still decides** (1–0 → that verdict), but the vote count travels with it so the UI shows the decision rests on one seat.
- **No judge returned** → `verdict: null`, rendered as "No Verdict".

Shape (`final_verdict` on the trial doc, and the `final_verdict` SSE event):

```json
{"verdict": "guilty|not_guilty|null", "guilty_votes": 2, "not_guilty_votes": 1, "failed_votes": 0, "tie_break": false, "unanimous": false}
```

Computed once in the orchestrator after the judges resolve, persisted with the trial, and emitted as its own SSE event before `done` so the live page needs no refetch. `GET /trials` and `GET /trials/{id}` recompute it on read for trials written before the field existed, so old rows in the archive are not blank. Displayed on both the trial page and every history row.

### Model configuration (same vs distinct)

- Per-trial toggle: user picks `model_mode: "same" | "distinct"` on the submission form, sent with `POST /trials`. No server restart needed to switch — both model pools are always configured server-side.
- `same`: all 7 participants (4 lawyers + 3 judges) use `SAME_MODEL`.
- `distinct`: each of the 7 participants uses its own env-configured model (`PROSECUTOR_1_MODEL` ... `JUDGE_3_MODEL`).
- Resolved per-call via `settings.model_for_role(role, model_mode)`; trial doc records the `model_mode` used for traceability. Two trials submitted back to back can use different modes.

### Token & cost controls
- `max_tokens` cap on every participant call (`AGENT_MAX_TOKENS`). On lawyers it bounds speech length, and so bounds every downstream judge prompt. On judges it is a correctness control, not just a cost one: with no cap the request inherits the provider's own default `max_completion_tokens`, and a reasoning-capable judge can exhaust it mid-`reasoning`, returning truncated JSON (or a bare `{}`) that fails the strict parse and burns the attempt budget.
- Cheap/free models for lawyers; stronger model reserved for judges.
- Log `usage` (prompt/completion tokens) per speech/verdict entry, from OpenRouter response.
- No retry loops beyond the bounded 3-attempt budget above. The budget is per participant and hard-capped: worst case is 21 model calls for a trial, never unbounded.
- No prompt caching.

### Free-tier hosting (pitfall: the backend is asleep when the grader arrives)

The backend runs on a free tier that spins down when idle and takes up to a minute to boot, so the *first* request after a quiet period is slow or briefly refused.

- The submission page fires `GET /health` on mount, so the backend starts waking while the charge sheet is being written — composing one usually covers most of the cold start.
- All frontend API calls go through `fetchWithWake`: 3 attempts with 1s/2s backoff, retrying connection failures and **502/503/504 only** (what a booting host and its proxy return). Every other status is a real answer and is surfaced as-is, so a 422 still fails immediately.
- A submit still pending after 4s shows "Waking the courthouse — the free hosting tier can take up to a minute", and a failed submit says the courthouse may still be waking rather than the generic "failed". A frozen button reads as a broken app; the message is the fix.
- `MONGO_SERVER_SELECTION_TIMEOUT_MS` is 10000, not 5000: a cold host's first Atlas connection pays SRV lookup, TLS and topology discovery, and a tighter bound turns a normal cold start into a 503.
- Known accepted gap: if the host is recycled mid-trial the doc stays `status: "running"` and the stream replies `already_completed` on reconnect, leaving that one trial unviewable. Deliberately not handled — re-running costs tokens and the window is small.

## Mongo Document Shape

```json
{
  "_id": ObjectId,
  "charge_sheet": "text",
  "created_at": ISODate,
  "status": "pending|running|completed",
  "speeches": [
    {"role": "prosecutor_1", "persona": "...", "model": "...", "status": "ok|failed", "content": "...", "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "attempts": 1, "error_reason": null, "error_code": null}
  ],
  "verdicts": [
    {"role": "judge_1", "persona": "...", "model": "...", "status": "ok|failed", "verdict": "guilty|not_guilty", "reasoning": "...", "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "attempts": 1, "error_reason": null, "error_code": null}
  ],
  "final_verdict": {"verdict": "guilty|not_guilty|null", "guilty_votes": 0, "not_guilty_votes": 0, "failed_votes": 0, "tie_break": false, "unanimous": false}
}
```

On a `failed` entry, `error_reason` holds the same plain-language sentence the user saw in the `error` event and `error_code` the failure class, so history/replay explains the failure instead of just flagging it. `attempts` records how many calls that participant actually consumed.

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
- `retry` — `{role, retry, max_retries, reason}` — an attempt for this role failed transiently and is being retried; `retry` is 1-based (`retry 1 of 2`), `reason` is the plain-language cause
- `error` — `{role, message, reason_code}` — role exhausted its attempts, or `role: "system"` for a trial-level failure (`persist_failed`, `internal`); `message` is user-facing prose
- `final_verdict` — `{verdict, guilty_votes, not_guilty_votes, failed_votes, tie_break, unanimous}` — the majority tally, emitted after the last verdict and before `done`
- `done` — `{trial_id}` — always the last event, emitted even after a `system` error

## Frontend Requirements

- Submission form: client-side length hint (20–4000 chars) mirroring backend validation, shows inline error on 422. Includes a same/distinct model toggle, sent as `model_mode` with the trial.
- Trial page: 4 speech cards + 3 verdict cards, pending state until each event lands. A `retry` event puts that card into a **retrying** state showing the count and cause ("Retrying — 1 of 2 · the provider is rate-limiting us"), so a slow retry never looks like a hang. A failed role shows an error state carrying the plain-language `message` from the `error` event — never a raw status code or provider payload. A `system` error renders as a trial-level banner (e.g. results shown but not saved).
- Trial page also shows the **final verdict banner** under the bench — the majority word, the vote tally (`2–1`), and a one-line caveat when the tally needs one (tie resolved for the defendant, only one judge ruled, N judges failed, or unanimous).
- History page: excerpt + the case's **final verdict chip** (word + tally, marked `· tie` when tie-broken), link to replay (fetches completed doc, no streaming). Falls back to the raw per-judge summary only for a trial with no verdicts at all.

## Explicitly Out of Scope

- Rebuttal / multi-round debate
- Auth / multi-user
- Ground-truth verdict / accuracy scoring
- Cloud deploy config
- Any *model-driven* consensus step — a deliberating or aggregating agent. The final verdict is a plain arithmetic tally (see above), not another judge.

## Verification Checklist

- `POST /trials` with charge sheet <20 chars → 422, no doc created.
- `POST /trials` with charge sheet >4000 chars → 422, no doc created.
- Valid charge sheet → 4 speech events, then 3 verdict events, then done, in order.
- Bad model id (simulated failure) → `error` event for that role with `reason_code: "model_unavailable"`, **no retry attempted** (permanent class), trial still completes with `done`.
- Simulated 429 / 5xx → `retry` events for that role numbered 1 of 2 then 2 of 2, with backoff between, before any `error`.
- Judge forced to return prose (bad model or prompt) → parse fails, retries within the shared budget, then `error` event with `reason_code: "invalid_verdict"` — verdict is never fabricated from partial prose. Total calls for that judge ≤ 3.
- Every `error` message shown to the user is prose, containing no HTTP status, exception class, or provider JSON.
- Mongo stopped mid-trial → final persist retried 3×, then `system` error event + `done`; stream still terminates, UI still shows the results it received.
- Mongo stopped before `POST /trials` → 503 with plain-language detail, not a 500 traceback.
- Mongo doc after run: `speeches`/`verdicts` arrays reflect `ok`/`failed` status accurately and carry `error_reason`/`error_code` on failures; `/history` and replay show the same.
- Tally: 3–0 and 2–1 → `guilty`; 1–2 → `not_guilty`; 2–0 with one judge failed → `guilty`; 1–1 with one failed → `not_guilty` with `tie_break: true`; 1–0 → that verdict with the count shown; all three judges failed → `verdict: null` / "No Verdict".
- A trial persisted before `final_verdict` existed still shows a final verdict in history and replay (recomputed on read).
