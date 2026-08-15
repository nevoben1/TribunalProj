export type SpeechCardState = {
  role: string;
  status: "pending" | "ok" | "failed";
  content?: string | null;
};

const ROLE_LABELS: Record<string, string> = {
  prosecutor_1: "Prosecutor I",
  prosecutor_2: "Prosecutor II",
  defender_1: "Defender I",
  defender_2: "Defender II",
};

export default function SpeechCard({ role, status, content }: SpeechCardState) {
  return (
    <div className={`card speech-card status-${status}`}>
      <div className="card-header">
        <span className="role-label">{ROLE_LABELS[role] ?? role}</span>
        <span className={`status-badge status-${status}`}>{status}</span>
      </div>
      <div className="card-body">
        {status === "pending" && <p className="muted">Waiting for speech…</p>}
        {status === "failed" && <p className="error-text">Speech generation failed.</p>}
        {status === "ok" && <p>{content}</p>}
      </div>
    </div>
  );
}
