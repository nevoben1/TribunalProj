"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  getTrial,
  streamTrial,
  SpeechEntry,
  VerdictEntry,
  Trial,
  FinalVerdict,
} from "@/lib/api";
import FinalVerdictBanner from "@/components/FinalVerdictBanner";
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
    errorReason: entry.error_reason,
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
    errorReason: entry.error_reason,
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
  const [systemError, setSystemError] = useState<string | null>(null);
  const [finalVerdict, setFinalVerdict] = useState<FinalVerdict | null>(null);

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
        setFinalVerdict(trial.final_verdict);
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
        onRetry: (data) => {
          const retry = {
            retry: data.retry,
            max_retries: data.max_retries,
            reason: data.reason,
          };
          setSpeeches((prev) =>
            prev.map((s) =>
              s.role === data.role ? { ...s, status: "retrying", retry } : s
            )
          );
          setVerdicts((prev) =>
            prev.map((v) =>
              v.role === data.role ? { ...v, status: "retrying", retry } : v
            )
          );
        },
        onError: (data) => {
          // role "system" is a trial-level failure (e.g. results not saved),
          // not one participant's — it belongs in a banner, not a card.
          if (data.role === "system") {
            setSystemError(data.message);
            return;
          }
          setSpeeches((prev) =>
            prev.map((s) =>
              s.role === data.role
                ? { role: data.role, status: "failed", errorReason: data.message }
                : s
            )
          );
          setVerdicts((prev) =>
            prev.map((v) =>
              v.role === data.role
                ? { role: data.role, status: "failed", errorReason: data.message }
                : v
            )
          );
        },
        onFinalVerdict: (data) => setFinalVerdict(data),
        onDone: () => {
          setDone(true);
          // The stream is over: anything still waiting never arrived, so
          // resolve it rather than leaving a card spinning forever.
          const stranded = "This participant never reported back before the trial closed.";
          setSpeeches((prev) =>
            prev.map((s) =>
              s.status === "pending" || s.status === "retrying"
                ? { role: s.role, status: "failed", errorReason: stranded }
                : s
            )
          );
          setVerdicts((prev) =>
            prev.map((v) =>
              v.status === "pending" || v.status === "retrying"
                ? { role: v.role, status: "failed", errorReason: stranded }
                : v
            )
          );
        },
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
      {systemError && <p className="system-banner">{systemError}</p>}
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

      {finalVerdict && <FinalVerdictBanner final={finalVerdict} />}

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
