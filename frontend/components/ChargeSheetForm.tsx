"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiValidationError, createTrial, ModelMode, warmBackend } from "@/lib/api";

const MIN_LEN = 20;
const MAX_LEN = 4000;
// Past this, the delay is a cold backend rather than a slow request; say so
// instead of leaving a frozen button that reads as a broken app.
const SLOW_SUBMIT_MS = 4000;

export default function ChargeSheetForm() {
  const router = useRouter();
  const [chargeSheet, setChargeSheet] = useState("");
  const [modelMode, setModelMode] = useState<ModelMode>("same");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [slow, setSlow] = useState(false);
  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Start the backend waking while the charge sheet is still being written —
  // composing one usually covers most of a cold start.
  useEffect(() => {
    warmBackend();
    return () => {
      if (slowTimer.current) clearTimeout(slowTimer.current);
    };
  }, []);

  const length = chargeSheet.length;
  const tooShort = length > 0 && length < MIN_LEN;
  const tooLong = length > MAX_LEN;
  const canSubmit = length >= MIN_LEN && length <= MAX_LEN && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    slowTimer.current = setTimeout(() => setSlow(true), SLOW_SUBMIT_MS);
    try {
      const { id } = await createTrial(chargeSheet, modelMode);
      router.push(`/trial/${id}`);
    } catch (err) {
      if (err instanceof ApiValidationError) {
        setError("Charge sheet must be between 20 and 4000 characters.");
      } else {
        setError(
          "The courthouse could not be reached. It may still be waking up — " +
            "please try again in a moment."
        );
      }
      setSubmitting(false);
    } finally {
      if (slowTimer.current) clearTimeout(slowTimer.current);
      setSlow(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="charge-sheet-form">
      <label htmlFor="charge_sheet">Charge sheet</label>
      <textarea
        id="charge_sheet"
        rows={8}
        value={chargeSheet}
        onChange={(e) => setChargeSheet(e.target.value)}
        placeholder="Describe the alleged offense in free text..."
      />
      <div className={`char-count ${tooShort || tooLong ? "char-count-invalid" : ""}`}>
        {length} / {MAX_LEN} characters
        {tooShort && ` (min ${MIN_LEN})`}
        {tooLong && " (too long)"}
      </div>

      <fieldset className="model-mode-toggle">
        <legend>Model configuration</legend>
        <label>
          <input
            type="radio"
            name="model_mode"
            value="same"
            checked={modelMode === "same"}
            onChange={() => setModelMode("same")}
          />
          Same model for all participants
        </label>
        <label>
          <input
            type="radio"
            name="model_mode"
            value="distinct"
            checked={modelMode === "distinct"}
            onChange={() => setModelMode("distinct")}
          />
          Distinct model per participant
        </label>
      </fieldset>

      {error && <p className="error-text">{error}</p>}
      {slow && (
        <p className="muted">
          Waking the courthouse — the free hosting tier can take up to a minute
          to start. Please stay on this page.
        </p>
      )}

      <button type="submit" disabled={!canSubmit}>
        {submitting ? "Starting trial…" : "Start Trial"}
      </button>
    </form>
  );
}
