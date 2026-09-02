const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type ModelMode = "same" | "distinct";

export type Usage = {
  prompt_tokens: number;
  completion_tokens: number;
  cost: number | null;
};

export type SpeechEntry = {
  role: string;
  persona: string;
  model: string;
  status: "ok" | "failed";
  content: string | null;
  usage: Usage | null;
  attempts?: number;
  error_reason?: string | null;
  error_code?: string | null;
};

export type VerdictEntry = {
  role: string;
  persona: string;
  model: string;
  status: "ok" | "failed";
  verdict: "guilty" | "not_guilty" | null;
  reasoning: string | null;
  usage: Usage | null;
  attempts?: number;
  error_reason?: string | null;
  error_code?: string | null;
};

export type FinalVerdict = {
  verdict: "guilty" | "not_guilty" | null;
  guilty_votes: number;
  not_guilty_votes: number;
  failed_votes: number;
  tie_break: boolean;
  unanimous: boolean;
};

export type Trial = {
  id: string;
  charge_sheet: string;
  created_at: string;
  status: "pending" | "running" | "completed";
  model_mode: ModelMode;
  speeches: SpeechEntry[];
  verdicts: VerdictEntry[];
  final_verdict: FinalVerdict | null;
};

export type TrialSummary = {
  id: string;
  charge_sheet_excerpt: string;
  created_at: string;
  status: "pending" | "running" | "completed";
  model_mode: ModelMode;
  verdict_summary: string[];
  final_verdict: FinalVerdict | null;
};

export class ApiValidationError extends Error {
  detail: unknown;
  constructor(detail: unknown) {
    super("validation failed");
    this.detail = detail;
  }
}

/**
 * Nudge the backend awake. The host sleeps when idle and takes up to a minute
 * to boot, so we start that clock while the user is still typing rather than
 * making them wait for it at submit time. Failures are irrelevant — the point
 * is the request arriving, not its answer.
 */
export function warmBackend(): void {
  fetch(`${API_BASE}/health`, { cache: "no-store" }).catch(() => {});
}

const ATTEMPTS = 3;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * fetch with the same retry discipline the backend uses. A sleeping host
 * answers the first request of the day with a connection error or a 502-504
 * from the platform's proxy, which is transient by definition; every other
 * status is a real answer and returned untouched for the caller to read.
 */
async function fetchWithWake(path: string, init?: RequestInit): Promise<Response> {
  let lastError: Error = new Error(`request failed: ${path}`);

  for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
    try {
      const res = await fetch(`${API_BASE}${path}`, init);
      if (res.status < 502 || res.status > 504) return res;
      lastError = new Error(`request failed: ${res.status}`);
    } catch (e) {
      lastError = e instanceof Error ? e : new Error(String(e));
    }
    if (attempt < ATTEMPTS) await sleep(1000 * 2 ** (attempt - 1));
  }

  throw lastError;
}

export async function createTrial(
  chargeSheet: string,
  modelMode: ModelMode
): Promise<{ id: string }> {
  const res = await fetchWithWake("/trials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ charge_sheet: chargeSheet, model_mode: modelMode }),
  });
  if (res.status === 422) {
    const body = await res.json();
    throw new ApiValidationError(body.detail);
  }
  if (!res.ok) {
    throw new Error(`create trial failed: ${res.status}`);
  }
  return res.json();
}

export async function listTrials(
  skip = 0,
  limit = 20
): Promise<TrialSummary[]> {
  const res = await fetchWithWake(`/trials?skip=${skip}&limit=${limit}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`list trials failed: ${res.status}`);
  return res.json();
}

export async function getTrial(id: string): Promise<Trial> {
  const res = await fetchWithWake(`/trials/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`get trial failed: ${res.status}`);
  return res.json();
}

type StreamHandlers = {
  onSpeech: (data: {
    role: string;
    content: string;
    model: string;
    usage: Usage | null;
  }) => void;
  onVerdict: (data: {
    role: string;
    verdict: string;
    reasoning: string;
    model: string;
    usage: Usage | null;
  }) => void;
  onRetry: (data: {
    role: string;
    retry: number;
    max_retries: number;
    reason: string;
  }) => void;
  onError: (data: {
    role: string;
    message: string;
    reason_code?: string;
  }) => void;
  onFinalVerdict: (data: FinalVerdict) => void;
  onDone: () => void;
};

export function streamTrial(id: string, handlers: StreamHandlers): () => void {
  const source = new EventSource(`${API_BASE}/trials/${id}/stream`);

  source.addEventListener("speech", (e) => {
    handlers.onSpeech(JSON.parse((e as MessageEvent).data));
  });
  source.addEventListener("verdict", (e) => {
    handlers.onVerdict(JSON.parse((e as MessageEvent).data));
  });
  source.addEventListener("final_verdict", (e) => {
    handlers.onFinalVerdict(JSON.parse((e as MessageEvent).data));
  });
  source.addEventListener("retry", (e) => {
    handlers.onRetry(JSON.parse((e as MessageEvent).data));
  });
  source.addEventListener("error", (e) => {
    const msgEvent = e as MessageEvent;
    if (msgEvent.data) {
      handlers.onError(JSON.parse(msgEvent.data));
    }
  });
  source.addEventListener("done", () => {
    handlers.onDone();
    source.close();
  });

  return () => source.close();
}
