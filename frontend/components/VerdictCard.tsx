export type VerdictCardState = {
  role: string;
  status: "pending" | "ok" | "failed";
  verdict?: "guilty" | "not_guilty" | null;
  reasoning?: string | null;
};

const ROLE_LABELS: Record<string, string> = {
  judge_1: "Judge I",
  judge_2: "Judge II",
  judge_3: "Judge III",
};

export default function VerdictCard({ role, status, verdict, reasoning }: VerdictCardState) {
  return (
    <div className={`card verdict-card status-${status}`}>
      <div className="card-header">
        <span className="role-label">{ROLE_LABELS[role] ?? role}</span>
        <span className={`status-badge status-${status}`}>{status}</span>
      </div>
      <div className="card-body">
        {status === "pending" && <p className="muted">Deliberating…</p>}
        {status === "failed" && <p className="error-text">Verdict generation failed.</p>}
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
