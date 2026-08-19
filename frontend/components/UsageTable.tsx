import { Usage } from "@/lib/api";
import { LAWYER_ROLE_LABELS } from "./SpeechCard";
import { JUDGE_ROLE_LABELS } from "./VerdictCard";

const ROLE_LABELS: Record<string, string> = { ...LAWYER_ROLE_LABELS, ...JUDGE_ROLE_LABELS };

export type UsageRow = {
  role: string;
  model?: string | null;
  usage?: Usage | null;
};

export default function UsageTable({ rows }: { rows: UsageRow[] }) {
  return (
    <div className="usage-table-wrap">
      <table className="usage-table">
        <thead>
          <tr>
            <th>Participant</th>
            <th>Model</th>
            <th>Prompt</th>
            <th>Completion</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const prompt = row.usage?.prompt_tokens ?? 0;
            const completion = row.usage?.completion_tokens ?? 0;
            return (
              <tr key={row.role}>
                <td>{ROLE_LABELS[row.role] ?? row.role}</td>
                <td className="usage-model">{row.model ?? "—"}</td>
                <td>{row.usage ? prompt : "—"}</td>
                <td>{row.usage ? completion : "—"}</td>
                <td>{row.usage ? prompt + completion : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
