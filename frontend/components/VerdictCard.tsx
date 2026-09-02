import { Usage } from "@/lib/api";

export type VerdictCardState = {
  role: string;
  status: "pending" | "retrying" | "ok" | "failed";
  verdict?: "guilty" | "not_guilty" | null;
  reasoning?: string | null;
  model?: string | null;
  usage?: Usage | null;
  retry?: { retry: number; max_retries: number; reason: string } | null;
  errorReason?: string | null;
};

export const JUDGE_ROLE_LABELS: Record<string, string> = {
  judge_1: "Judge I",
  judge_2: "Judge II",
  judge_3: "Judge III",
};

const ROLE_LABELS = JUDGE_ROLE_LABELS;

export default function VerdictCard({
  role,
  status,
  verdict,
  reasoning,
  retry,
  errorReason,
}: VerdictCardState) {
  return (
    <div className={`card verdict-card status-${status}`}>
      <div className="card-header">
        <span className="role-label">{ROLE_LABELS[role] ?? role}</span>
        <span className={`status-badge status-${status}`}>
          {status === "retrying" && retry
            ? `retrying ${retry.retry}/${retry.max_retries}`
            : status}
        </span>
      </div>
      <div className="card-body">
        {status === "pending" && <p className="muted">Deliberating…</p>}
        {status === "retrying" && retry && (
          <p className="retry-text">
            Retrying — attempt {retry.retry} of {retry.max_retries} — {retry.reason}.
          </p>
        )}
        {status === "failed" && (
          <p className="error-text">
            {errorReason ?? "This judge could not return a verdict."}
          </p>
        )}
        {status === "ok" && verdict && (
          <>
            <p className={`verdict-badge verdict-${verdict}`}>
              {verdict === "guilty" ? "Guilty" : "Not Guilty"}
            </p>
            <p>{reasoning}</p>
          </>
        )}
      </div>
    </div>
  );
}
