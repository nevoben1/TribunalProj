import { Usage } from "@/lib/api";
import { LAWYER_ROLE_LABELS } from "./SpeechCard";
import { JUDGE_ROLE_LABELS } from "./VerdictCard";

const ROLE_LABELS: Record<string, string> = { ...LAWYER_ROLE_LABELS, ...JUDGE_ROLE_LABELS };

export type UsageRow = {
  role: string;
  model?: string | null;
  usage?: Usage | null;
};

function formatCost(cost: number | null | undefined): string {
  if (cost == null) return "—";
  if (cost === 0) return "$0.00";
  return `$${cost.toFixed(6)}`;
}

export default function UsageTable({ rows }: { rows: UsageRow[] }) {
  const totalCost = rows.reduce((sum, row) => sum + (row.usage?.cost ?? 0), 0);
  const hasAnyCost = rows.some((row) => row.usage?.cost != null);

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
            <th>Price</th>
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
                <td>{formatCost(row.usage?.cost)}</td>
              </tr>
            );
          })}
        </tbody>
        {hasAnyCost && (
          <tfoot>
            <tr>
              <td colSpan={5}>Total</td>
              <td>{formatCost(totalCost)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
