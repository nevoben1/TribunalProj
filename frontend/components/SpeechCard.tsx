import { Usage } from "@/lib/api";

export type SpeechCardState = {
  role: string;
  status: "pending" | "retrying" | "ok" | "failed";
  content?: string | null;
  model?: string | null;
  usage?: Usage | null;
  retry?: { retry: number; max_retries: number; reason: string } | null;
  errorReason?: string | null;
};

export const LAWYER_ROLE_LABELS: Record<string, string> = {
  prosecutor_1: "Prosecutor I",
  prosecutor_2: "Prosecutor II",
  defender_1: "Defender I",
  defender_2: "Defender II",
};

const ROLE_LABELS = LAWYER_ROLE_LABELS;

export default function SpeechCard({
  role,
  status,
  content,
  retry,
  errorReason,
}: SpeechCardState) {
  return (
    <div className={`card speech-card status-${status}`}>
      <div className="card-header">
        <span className="role-label">{ROLE_LABELS[role] ?? role}</span>
        <span className={`status-badge status-${status}`}>
          {status === "retrying" && retry
            ? `retrying ${retry.retry}/${retry.max_retries}`
            : status}
        </span>
      </div>
      <div className="card-body">
        {status === "pending" && <p className="muted">Waiting for speech…</p>}
        {status === "retrying" && retry && (
          <p className="retry-text">
            Retrying — attempt {retry.retry} of {retry.max_retries} — {retry.reason}.
          </p>
        )}
        {status === "failed" && (
          <p className="error-text">
            {errorReason ?? "This speech could not be delivered."}
          </p>
        )}
        {status === "ok" && <p>{content}</p>}
      </div>
    </div>
  );
}
