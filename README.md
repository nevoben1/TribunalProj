# AI Tribunal

A courtroom simulation run by seven AI agents. You submit a free-text **charge sheet**; four AI lawyers argue the case, three AI judges rule on it independently, and a final verdict is decided by majority. Speeches and verdicts stream into the page live as each agent finishes.

> **Live app:** _<fill in Vercel URL>_
> **API:** _<fill in Render URL>_
>
> **Before you start: the backend sleeps.** The free hosting tier shuts the API down when nobody has used it, and the first visit of the day takes **up to a minute** to wake it. This is expected, it is handled, and [what to do about it is explained below](#the-first-visit-is-slow-this-is-normal).

## How a trial works

1. You write a charge sheet — free text, anywhere from 20 to 4000 characters. No fixed format; describe an alleged offence however you like.
2. You pick a **model configuration**: *same model for all participants*, or *a distinct model per participant*. Switchable per trial, no restart.
3. Four lawyers speak in order — two prosecutors, then two defenders. Each has its own persona and speaks once; there are no rebuttals.
4. Three judges then read the charge sheet plus all four speeches and each return a verdict (`guilty` / `not guilty`) with written reasoning. They rule in parallel and never see each other's verdicts.
5. A **final verdict** is computed as a plain majority of the judges who ruled. Every trial is saved and can be replayed from **Case History**.

The whole run takes roughly one to three minutes depending on the models.

### How the final verdict is decided

It is arithmetic over the verdicts already returned — no extra AI call, no aggregating agent:

- Only judges who actually ruled get a vote. A judge that failed is **excluded**, not counted as an acquittal.
- More guilty than not-guilty votes → **guilty**. Otherwise → **not guilty**.
- **A tie goes to the defendant** (1–1 → not guilty), as in a bench with no majority to convict. The page says so explicitly rather than implying the judges chose acquittal.
- If only one judge survived, that verdict stands but the page shows it rests on a single seat (`1–0`).
- If all three judges failed, the result is **No Verdict** — never a guessed one.

The vote tally is always displayed next to the verdict, so you can see exactly what the bench did.

## The first visit is slow — this is normal

The backend is hosted on a free tier that spins the service down after a period without traffic. Waking it takes up to a minute. The app is built to absorb this:

- Opening the submission page immediately pings the backend, so it starts waking **while you write your charge sheet**. Composing one usually covers most of the wait.
- Every request retries automatically — three attempts with backoff — on the connection errors and gateway errors a booting server produces.
- If a submission takes more than four seconds, the page tells you the courthouse is waking and asks you to stay on the page.

**What you should do:** open the app, start typing, and submit normally. If the very first submission fails anyway, **press Start Trial again** — by then the server is almost certainly awake.

The database is on a free tier too, and can take a few extra seconds on its first connection. Same advice.

## If something fails during a trial

Individual agents can fail — free-tier models time out, get rate-limited, or return unusable text. **A failed agent never stops the trial.** The other six carry on and the trial still reaches a verdict.

Each participant gets **three attempts** (two retries), and you can watch it happen:

| What you see | What it means |
|---|---|
| A card marked **retrying 1/2** with a reason | That agent's call failed for a temporary reason and is being retried automatically. Wait — there is nothing to do. |
| A card marked **failed** with a sentence explaining why | That agent used up all its attempts. The trial continues without it. |
| A banner above the cards | A trial-level problem, most often that the results could not be saved. What is on screen is still complete and correct. |
| **No Verdict** as the final result | All three judges failed. Rare, and usually means the configured model is having a bad day. |

Failures that cannot be fixed by retrying — a mistyped model name, a rejected API key — fail immediately rather than making you wait through pointless retries. The reason is always written in plain language; raw error codes stay in the server logs.

### What to do about each outcome

| Symptom | What to do |
|---|---|
| One lawyer or judge failed, verdict still reached | Nothing. This is the system working as designed. Run another trial if you want a clean sheet. |
| Several agents failed in the same trial | The free model is overloaded. Wait a minute and run it again, or switch the model configuration toggle to the other setting. |
| "The courthouse could not be reached" on submit | The backend is still waking. Press Start Trial again. |
| Case History shows "Failed to load" | Same cause — reload the page once. |
| A trial page shows results but a banner says they were not saved | The results on screen are valid; that one trial just will not appear in Case History. |
| The page sits on "pending" cards and never finishes | Reload. If the trial had already started, its results were saved and the page will replay them. |

**A note on one known gap:** if the free-tier host happens to restart in the middle of a trial, that trial is left in a half-finished state and its page will come back empty. It is rare, it affects only that one trial, and starting a new trial always works. We left it unhandled deliberately — re-running a trial costs API tokens for no benefit.

## Running it locally

**Backend** (Python 3.11+):

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                 # then fill in OPENROUTER_API_KEY and MONGO_URI
uvicorn app.main:app --reload
```

Runs on `http://localhost:8000`. `GET /health` confirms both the API and the database are reachable.

**Frontend** (Node 20+):

```bash
cd frontend
npm install
npm run dev
```

Runs on `http://localhost:3000`. Set `NEXT_PUBLIC_API_BASE` if the backend is not on `localhost:8000`.

### Configuration

All backend settings live in `backend/.env` — see [`.env.example`](backend/.env.example) for the full list with comments. The ones that matter:

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter credentials. Required. |
| `MONGO_URI` | Mongo connection string. Required. |
| `SAME_MODEL` | The model used by all seven participants in *same* mode. |
| `PROSECUTOR_1_MODEL` … `JUDGE_3_MODEL` | Per-participant models used in *distinct* mode. |
| `AGENT_MAX_ATTEMPTS` | Attempts per participant, shared across call and parse failures. Default 3. |
| `LAWYER_MAX_TOKENS` | Caps speech length, which is what keeps judge prompts (and cost) down. |

Model ids are never hardcoded — both pools are configured here, and the user picks between them per trial.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/trials` | Create a trial from `{charge_sheet, model_mode}`. Rejects a charge sheet outside 20–4000 characters with 422, before anything is created. |
| `GET` | `/trials/{id}/stream` | Server-sent events; running the trial starts on first connection. Emits `speech`, `verdict`, `retry`, `error`, `final_verdict`, then always `done`. |
| `GET` | `/trials` | Paginated history. |
| `GET` | `/trials/{id}` | Full trial for replay. |
| `GET` | `/health` | Liveness, including a database ping. |

## Project layout

```
backend/app/
  main.py            FastAPI app, CORS, health
  routes/trials.py   the four trial endpoints
  orchestrator.py    runs the trial, emits the event stream
  agents/base.py     OpenRouter client: timeouts, failure classification, retries
  agents/lawyer.py   speech generation
  agents/judge.py    verdict generation + strict JSON parsing
  agents/personas.py the seven system prompts
  models/trial.py    document models + the majority tally
  db.py              Mongo client and retry helper
frontend/
  app/               submission, live trial, history pages
  components/        speech / verdict / final-verdict / usage views
  lib/api.ts         fetch helpers with wake-up retries, SSE client
```

Design documents: [architecture.md](architecture.md) for the layout and reasoning, [specs.md](specs.md) for the full behaviour contract, [token-economy.md](token-economy.md) for cost analysis.

## Deliberately out of scope

Rebuttals and multi-round debate, authentication, ground-truth accuracy scoring, and any AI-driven consensus step between the judges — the final verdict is a tally, by design.
