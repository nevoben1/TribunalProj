# AI Tribunal — Architecture Plan

## Context

Class project (solo, rolling through semester, no rush). A web app simulates a courtroom: user submits a free-text charge sheet, 4 AI lawyer agents (2 prosecutors, 2 defenders, distinct personas) each generate a one-shot speech via OpenRouter, then 3 AI judge agents independently review the charge sheet + all 4 speeches and each render a verdict (Guilty / Not Guilty) with written reasoning. The 3 verdicts are shown side by side and reduced to a final verdict by a deterministic majority tally (tie goes to the defendant) — no deliberation round and no aggregating model call. User watches speeches and verdicts stream in live. Past trials are saved for browsing later. No auth yet, no ground-truth scoring. Deploy later to cloud, build locally first.

This is a greenfield project — no existing code to trace. Plan below defines project layout and component responsibilities so implementation can proceed piece by piece over the semester.

## High-Level Architecture

```
┌─────────────────┐      SSE stream       ┌──────────────────────┐      HTTPS       ┌────────────┐
│  Next.js (web)   │ <──────────────────── │  FastAPI (backend)    │ ───────────────> │ OpenRouter │
│  - submit form   │  POST /trials (start) │  - trial orchestrator │                  │   (LLMs)   │
│  - live trial UI │ ────────────────────> │  - agent runner       │ <─────────────── │            │
│  - history page  │                       │  - SSE endpoint        │                  └────────────┘
└─────────────────┘                       └──────────┬────────────┘
                                                       │ motor/pymongo
                                                       v
                                              ┌──────────────────┐
                                              │  MongoDB Atlas    │
                                              │  trials collection│
                                              └──────────────────┘
```

## Backend (Python / FastAPI)

**Project layout:**
```
backend/
  app/
    main.py                 # FastAPI app, CORS, router mounting
    config.py                # env vars: OPENROUTER_API_KEY, MONGO_URI, model ids per role
    models/
      trial.py                # Pydantic models: ChargeSheet, Speech, Verdict, Trial
    agents/
      base.py                  # generic OpenRouter chat-completion caller (async httpx)
      personas.py               # system prompts for prosecutor1/2, defender1/2, judge1/2/3
      lawyer.py                  # run_lawyer_speech(charge_sheet, persona) -> Speech
      judge.py                   # run_judge_verdict(charge_sheet, speeches, persona) -> Verdict
    orchestrator.py           # run_trial(charge_sheet) -> async generator yielding SSE events
    routes/
      trials.py                # POST /trials (create+stream), GET /trials, GET /trials/{id}
    db.py                     # motor async Mongo client, get_collection()
  requirements.txt
  .env.example
```

**Key design points:**
- `orchestrator.py` is the core: an async generator that runs lawyers sequentially in fixed order (Pros1, Pros2, Def1, Def2), yields an SSE event after each speech completes, then runs the 3 judges (can run in parallel via `asyncio.gather` since they're independent of each other, only depend on prior speeches), yielding an SSE event per verdict. At the end it persists the full trial document to Mongo and yields a "done" event with the trial id.
- `agents/base.py` wraps OpenRouter's OpenAI-compatible `/chat/completions` endpoint with async httpx, takes `model`, `system_prompt`, `user_prompt`, returns text. Centralizes retry/timeout/error handling so lawyer/judge modules stay thin.
- `agents/personas.py` holds one system prompt + model id per of the 7 roles — single place to tune personas and swap models later.
- SSE endpoint: `POST /trials` accepts `{charge_sheet: str}`, returns `text/event-stream`. Each event is JSON: `{type: "speech"|"verdict"|"done"|"error", role, content, ...}`.
- Error handling: agent failures are classified (transient vs permanent), transient ones retried within a per-participant 3-attempt budget with backoff, and each retry surfaced to the user as a `retry` event. If the budget runs out, yield an `error` event for that role carrying a plain-language reason, and continue the trial rather than aborting entirely — a single flaky free-tier model shouldn't kill the whole run. Mongo calls go through the same retry discipline; the final persist is the protected path, and the stream always ends in `done`. Full contract in [specs.md](specs.md).
- `GET /trials` (paginated list for history page) and `GET /trials/{id}` (full replay of a past trial, non-streaming) read straight from Mongo.

**Mongo document shape (`trials` collection):**
```json
{
  "_id": ObjectId,
  "charge_sheet": "text",
  "created_at": ISODate,
  "speeches": [
    {"role": "prosecutor_1", "persona": "...", "model": "...", "content": "..."},
    ...
  ],
  "verdicts": [
    {"role": "judge_1", "persona": "...", "model": "...", "verdict": "guilty|not_guilty", "reasoning": "..."},
    ...
  ],
  "final_verdict": {"verdict": "guilty|not_guilty|null", "guilty_votes": 0, "not_guilty_votes": 0, "failed_votes": 0, "tie_break": false, "unanimous": false}
}
```
No relational joins needed — one document per trial is a natural fit, matches your Mongo Atlas call.

## Frontend (Next.js)

**Project layout:**
```
frontend/
  app/
    page.tsx                  # charge sheet submission form
    trial/[id]/page.tsx        # live/replay trial view (speeches + verdicts)
    history/page.tsx           # list of past trials
  lib/
    api.ts                     # fetch helpers, SSE client (EventSource wrapper)
  components/
    SpeechCard.tsx
    VerdictCard.tsx
    ChargeSheetForm.tsx
```

- Submission form posts charge sheet, backend kicks off trial and returns a stream (or a trial id to open an SSE connection against, e.g. `GET /trials/{id}/stream` pattern — decide based on whether POST-with-streaming-response or POST-then-GET-stream is cleaner; POST-then-GET-stream avoids SSE-over-POST client quirks with `EventSource`, which only supports GET — **recommend that**: `POST /trials` creates a pending trial + returns id immediately, `GET /trials/{id}/stream` is the actual `EventSource` source, orchestration runs on first stream connection).
- Trial page renders 4 speech cards appearing in order as SSE events arrive, then 3 verdict cards, each with a loading/pending state until its event lands.
- History page lists past trials (charge sheet excerpt + 3 verdicts summary), links to replay view which just fetches the completed document (no streaming needed).

## Token & Cost Management

The expensive call is the judge call: each of the 3 judges receives charge sheet + all 4 speeches, so speech length compounds 3x. Levers to keep this bounded:

- **Cap speech length via `max_tokens`** on lawyer calls (e.g. 250–400 tokens each). Biggest single lever since it shrinks every downstream judge prompt.
- **Cheap/free models for lawyers, reserve any stronger/pricier model for judges only** — judges do more reasoning per call, so that's the right place to spend if spending at all.
- **Log token usage per call.** OpenRouter returns `usage` (prompt/completion tokens) on every response — store it per speech/verdict entry on the trial document. Free to capture, gives real cost data instead of guesswork, useful for the class writeup.
- **Bounded 3-attempt budget per participant (2 retries), and only for transient failures** — no retry loops, and a permanent failure (bad model id, auth, 400) fails immediately instead of paying for two more calls. Worst case is 21 model calls per trial, never unbounded.
- **Skip prompt caching** — not worth the complexity; the charge sheet (bulk of the prompt) changes every trial, and system prompts alone are small, so there's no meaningful static prefix to cache.

Mongo document gets a `usage` field per speech/verdict entry, e.g. `{"prompt_tokens": int, "completion_tokens": int}`, so historical trials carry their own cost trail.

## Open items to revisit later (explicitly deferred, not blocking)

- Rebuttal / multi-round debate flow (you said might come later)
- Auth / multi-user
- Ground-truth verdict field for accuracy analysis
- Cloud deploy config (Vercel + Render/Railway + Atlas)

## Verification (once built)

- Run FastAPI locally (`uvicorn app.main:app --reload`), hit `POST /trials` with curl + a sample charge sheet, confirm Mongo document created and SSE events stream in order (4 speeches, then 3 verdicts, then done).
- Run Next.js dev server, submit a real charge sheet through the form, watch cards populate live, then check `/history` shows the new trial and replay works.
- Test one deliberately bad case (e.g. empty charge sheet) to confirm validation error surfaces cleanly, and one simulated model failure (bad model id) to confirm the per-agent error handling doesn't crash the whole trial.

## What Makes This a Cognified Project

AI Tribunal is a cognified application in the literal sense: it takes a task that is inherently cognitive — legal reasoning, argumentation, and judgment — and distributes it across a network of AI agents, each playing a specialized role. The app is not just AI-assisted; the AI *is* the product. Without the 7 agent calls, there is no trial, no output, no value. Every meaningful action in the system — constructing an argument, weighing evidence, rendering a verdict — is performed by a language model, not a human and not a deterministic algorithm. The architecture reflects this: agents are first-class components with distinct personas, model assignments, and prompt contracts, not interchangeable utility functions. The multi-agent design also mirrors how cognition is distributed in real institutions — adversarial roles (prosecution vs. defense) force the reasoning space to be explored from opposing directions, while independent judges eliminate single-point-of-view bias in the outcome. The result is a system where the software scaffolding (FastAPI, Next.js, Mongo) exists purely to coordinate, stream, and persist cognitive work that the LLMs perform.
