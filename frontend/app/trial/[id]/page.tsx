"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { getTrial, streamTrial, SpeechEntry, VerdictEntry, Trial } from "@/lib/api";
import SpeechCard, { SpeechCardState } from "@/components/SpeechCard";
import VerdictCard, { VerdictCardState } from "@/components/VerdictCard";
import UsageTable from "@/components/UsageTable";

const LAWYER_ROLES = ["prosecutor_1", "prosecutor_2", "defender_1", "defender_2"];
const JUDGE_ROLES = ["judge_1", "judge_2", "judge_3"];

function initialSpeeches(): SpeechCardState[] {
  return LAWYER_ROLES.map((role) => ({ role, status: "pending" as const }));
}

function initialVerdicts(): VerdictCardState[] {
  return JUDGE_ROLES.map((role) => ({ role, status: "pending" as const }));
}

function fromSpeechEntry(entry: SpeechEntry): SpeechCardState {
  return {
    role: entry.role,
    status: entry.status,
    content: entry.content,
    model: entry.model,
    usage: entry.usage,
  };
}

function fromVerdictEntry(entry: VerdictEntry): VerdictCardState {
  return {
    role: entry.role,
    status: entry.status,
    verdict: entry.verdict,
    reasoning: entry.reasoning,
    model: entry.model,
    usage: entry.usage,
  };
}

export default function TrialPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [chargeSheet, setChargeSheet] = useState("");
  const [modelMode, setModelMode] = useState<string | null>(null);
  const [speeches, setSpeeches] = useState<SpeechCardState[]>(initialSpeeches());
  const [verdicts, setVerdicts] = useState<VerdictCardState[]>(initialVerdicts());
  const [done, setDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let stopStream: (() => void) | null = null;

    async function init() {
      let trial: Trial;
      try {
        trial = await getTrial(id);
      } catch {
        if (!cancelled) setNotFound(true);
        return;
      }
      if (cancelled) return;

      setChargeSheet(trial.charge_sheet);
      setModelMode(trial.model_mode);
      setLoading(false);

      if (trial.status === "completed") {
        setSpeeches(trial.speeches.map(fromSpeechEntry));
        setVerdicts(trial.verdicts.map(fromVerdictEntry));
        setDone(true);
        return;
      }

      stopStream = streamTrial(id, {
        onSpeech: (data) => {
          setSpeeches((prev) =>
            prev.map((s) =>
              s.role === data.role
                ? {
                    role: data.role,
                    status: "ok",
                    content: data.content,
                    model: data.model,
                    usage: data.usage,
                  }
                : s
            )
          );
        },
        onVerdict: (data) => {
          setVerdicts((prev) =>
            prev.map((v) =>
              v.role === data.role
                ? {
                    role: data.role,
                    status: "ok",
                    verdict: data.verdict as "guilty" | "not_guilty",
                    reasoning: data.reasoning,
                    model: data.model,
                    usage: data.usage,
                  }
                : v
            )
          );
        },
        onError: (data) => {
          setSpeeches((prev) =>
            prev.map((s) => (s.role === data.role ? { role: data.role, status: "failed" } : s))
          );
          setVerdicts((prev) =>
            prev.map((v) => (v.role === data.role ? { role: data.role, status: "failed" } : v))
          );
        },
        onDone: () => setDone(true),
      });
    }

    init();
    return () => {
      cancelled = true;
      stopStream?.();
    };
  }, [id]);

  if (notFound) {
    return (
      <main className="page">
        <p>Trial not found.</p>
        <Link href="/">Back to home</Link>
      </main>
    );
  }

  if (loading) {
    return (
      <main className="page">
        <p className="muted">Loading trial…</p>
      </main>
    );
  }

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <span className="kicker">{done ? "Verdict Rendered" : "In Session"}</span>
          <h1>The Proceedings</h1>
        </div>
        <Link href="/history">Case History →</Link>
      </div>
      <p className="charge-sheet-display">&ldquo;{chargeSheet}&rdquo;</p>
      {modelMode && (
        <p className="muted" style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem" }}>
          Model configuration: {modelMode}
        </p>
      )}

      <h2>Counsel</h2>
      <div className="card-grid">
        {speeches.map((s) => (
          <SpeechCard key={s.role} {...s} />
        ))}
      </div>

      <h2>The Bench</h2>
      <div className="card-grid">
        {verdicts.map((v) => (
          <VerdictCard key={v.role} {...v} />
        ))}
      </div>

      {done && (
        <>
          <h2>Token Usage</h2>
          <UsageTable rows={[...speeches, ...verdicts]} />
          <p className="muted">— Trial concluded —</p>
        </>
      )}
    </main>
  );
}
