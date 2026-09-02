import { FinalVerdict } from "@/lib/api";

export function verdictLabel(verdict: "guilty" | "not_guilty" | null): string {
  if (verdict === "guilty") return "Guilty";
  if (verdict === "not_guilty") return "Not Guilty";
  return "No Verdict";
}

export function voteTally(fv: FinalVerdict): string {
  return `${fv.guilty_votes}–${fv.not_guilty_votes}`;
}

/** The caveat that keeps a bare verdict word from overstating the bench. */
function qualifier(fv: FinalVerdict): string | null {
  if (fv.verdict === null) return "No judge returned a verdict in this trial.";
  if (fv.tie_break) {
    return "The bench split evenly, so the tie is resolved in the defendant's favour.";
  }
  if (fv.guilty_votes + fv.not_guilty_votes === 1) {
    return "Only one judge ruled; the other seats returned nothing.";
  }
  if (fv.failed_votes > 0) {
    return `${fv.failed_votes} judge${fv.failed_votes > 1 ? "s" : ""} failed to rule.`;
  }
  if (fv.unanimous) return "The bench was unanimous.";
  return null;
}

export default function FinalVerdictBanner({ final }: { final: FinalVerdict }) {
  const note = qualifier(final);
  return (
    <div className={`final-verdict verdict-${final.verdict ?? "none"}`}>
      <span className="final-verdict-kicker">The Bench Rules</span>
      <p className="final-verdict-word">{verdictLabel(final.verdict)}</p>
      {final.verdict !== null && (
        <p className="final-verdict-tally">
          {voteTally(final)} — guilty to not guilty
        </p>
      )}
      {note && <p className="final-verdict-note">{note}</p>}
    </div>
  );
}
