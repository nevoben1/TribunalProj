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
};

export type VerdictEntry = {
  role: string;
  persona: string;
  model: string;
  status: "ok" | "failed";
  verdict: "guilty" | "not_guilty" | null;
  reasoning: string | null;
  usage: Usage | null;
};

export type Trial = {
  id: string;
  charge_sheet: string;
  created_at: string;
  status: "pending" | "running" | "completed";
  model_mode: ModelMode;
  speeches: SpeechEntry[];
  verdicts: VerdictEntry[];
};

export type TrialSummary = {
  id: string;
  charge_sheet_excerpt: string;
  created_at: string;
  status: "pending" | "running" | "completed";
  model_mode: ModelMode;
  verdict_summary: string[];
};

export class ApiValidationError extends Error {
  detail: unknown;
  constructor(detail: unknown) {
    super("validation failed");
    this.detail = detail;
  }
}

export async function createTrial(
  chargeSheet: string,
  modelMode: ModelMode
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/trials`, {
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
  const res = await fetch(`${API_BASE}/trials?skip=${skip}&limit=${limit}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`list trials failed: ${res.status}`);
  return res.json();
}

export async function getTrial(id: string): Promise<Trial> {
  const res = await fetch(`${API_BASE}/trials/${id}`, { cache: "no-store" });
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
  onError: (data: { role: string; message: string }) => void;
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
