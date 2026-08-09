# Token Economy — AI Tribunal

## The Core Challenge

AI Tribunal is unusually token-expensive by design. A single trial involves 7 sequential LLM calls, and they are not independent — the output of the lawyer calls becomes input to the judge calls. This means token costs compound: every token a lawyer generates gets multiplied by 3 (once per judge). A trial where each of the 4 lawyers produces 400 tokens means each judge receives ~1,600 tokens of speech content on top of the charge sheet and its own system prompt. At 3 judges, that's roughly 5,000+ prompt tokens just for the verdict phase, before any judge output is counted. The architecture must treat token usage as a first-class concern, not an afterthought.

## Specific Challenges

### 1. Multiplicative Prompt Growth
The judge prompt is: `system_prompt + charge_sheet + all 4 speeches`. Speech length is the single biggest variable — it compounds 3x across judges. A lawyer that rambles to 800 tokens doesn't just cost 800 tokens; it costs an extra 1,200 tokens in downstream judge prompts. This is the highest-leverage problem to solve.

### 2. Seven Calls Per Trial, All Blocking Cost
Every trial is guaranteed to make 7 LLM calls with no option to skip or short-circuit (except on agent failure). There is no "cheap path" through the system. Even a trivial or absurd charge sheet pays the full cost. This makes per-trial cost predictable but means there's no free ride for light usage.

### 3. Free-Tier Model Unreliability
To manage cost, lawyers will run on free or cheap OpenRouter models. Free-tier models are rate-limited, slower, and more prone to timeout — which can trigger retries that silently double spend. The retry policy must be strict to prevent cost blowout from flaky model behavior.

### 4. No Shared Context Across Calls
Each of the 7 agent calls is stateless — there is no shared KV cache or prefix reuse across them. The charge sheet is re-sent in full to every agent. On most OpenRouter models, prompt caching is either unavailable or unreliable for short, unique prompts, so we cannot rely on it to reduce prompt token costs.

### 5. Opaque Spend Without Instrumentation
Without explicit token logging, there is no visibility into where cost is concentrated — whether it's lawyer verbosity, judge prompt size, or model choice. Flying blind makes tuning impossible.

## How We Plan to Overcome Them

### Cap Lawyer Output at the Source
Set `max_tokens` to 250–400 on all lawyer calls. This is the single most effective lever: it puts a hard ceiling on speech length, directly capping the size of every downstream judge prompt. The cap should be tuned by running a few real trials and reading the usage logs — 300 is a reasonable starting point.

### Tiered Model Assignment
Use free or low-cost models (e.g. `mistralai/mistral-7b-instruct` or similar free-tier options on OpenRouter) for the 4 lawyer calls. Reserve any stronger or paid model exclusively for the 3 judge calls, which do more complex reasoning and produce the final output the user cares about most. This concentrates spend where it matters.

### Strict Single-Retry Policy
If an agent call fails (timeout, rate limit, API error), retry exactly once with a short backoff. If it fails again, yield an `error` event for that role and continue the trial. No retry loops, no exponential backoff that silently keeps the call alive — one retry max, then move on.

### Per-Call Token Logging
OpenRouter returns a `usage` object (`prompt_tokens`, `completion_tokens`) on every response. We capture this and store it on the Mongo trial document alongside each speech and verdict entry. This gives us a real cost trail per trial and per role — without guessing. Over time, it shows exactly where tokens are going and what persona/model changes actually save.

### Prompt Discipline in Personas
System prompts in `agents/personas.py` are kept concise. Verbose system prompts eat into every call's prompt budget. Each persona gets a tight, role-focused prompt — no padding, no repetitive instructions. The charge sheet itself is the bulk of the variable content; the system prompt should be as small as possible.

### Deferred: Prompt Caching
Prompt caching (e.g. Anthropic's cache_control or OpenRouter's equivalent) is explicitly deferred. The charge sheet changes every trial, so there is no large static prefix to cache across calls. System prompts alone are too small to make caching worthwhile. If the project later adds a fixed preamble (e.g. a shared "court rules" block), caching can be revisited then.

## Summary Table

| Challenge | Mitigation | Lever Strength |
|---|---|---|
| Multiplicative judge prompt growth | Cap lawyer `max_tokens` (250–400) | High |
| All 7 calls are mandatory cost | Tiered model assignment (cheap lawyers, stronger judges) | High |
| Retry amplification from flaky models | Single-retry-max policy | Medium |
| No cross-call cache reuse | Accept it; deferred for later | Low (deferred) |
| No spend visibility | Log `usage` per call to Mongo | Enabling |
| Verbose system prompts | Keep personas concise | Low-Medium |
