"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listTrials, TrialSummary } from "@/lib/api";

export default function HistoryPage() {
  const [trials, setTrials] = useState<TrialSummary[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    listTrials()
      .then(setTrials)
      .catch(() => setError(true));
  }, []);

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <span className="kicker">The Archive</span>
          <h1>Case History</h1>
        </div>
        <Link href="/">+ New Trial</Link>
      </div>

      {error && <p className="error-text">Failed to load trial history.</p>}
      {!error && trials === null && <p className="muted">Loading…</p>}
      {trials !== null && trials.length === 0 && <p className="muted">No trials yet.</p>}

      <ul className="trial-list">
        {trials?.map((t) => (
          <li key={t.id} className="trial-list-item">
            <Link href={`/trial/${t.id}`}>
              <div className="trial-list-excerpt">{t.charge_sheet_excerpt}</div>
              <div className="trial-list-meta">
                <span>{new Date(t.created_at).toLocaleString()}</span>
                <span>{t.status}</span>
                <span>{t.model_mode}</span>
                <span>{t.verdict_summary.join(", ")}</span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
