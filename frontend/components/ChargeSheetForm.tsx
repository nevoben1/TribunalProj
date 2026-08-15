"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiValidationError, createTrial, ModelMode } from "@/lib/api";

const MIN_LEN = 20;
const MAX_LEN = 4000;

export default function ChargeSheetForm() {
  const router = useRouter();
  const [chargeSheet, setChargeSheet] = useState("");
  const [modelMode, setModelMode] = useState<ModelMode>("same");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const length = chargeSheet.length;
  const tooShort = length > 0 && length < MIN_LEN;
  const tooLong = length > MAX_LEN;
  const canSubmit = length >= MIN_LEN && length <= MAX_LEN && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const { id } = await createTrial(chargeSheet, modelMode);
      router.push(`/trial/${id}`);
    } catch (err) {
      if (err instanceof ApiValidationError) {
        setError("Charge sheet must be between 20 and 4000 characters.");
      } else {
        setError("Failed to submit charge sheet. Please try again.");
      }
      setSubmitting(false);
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

      <button type="submit" disabled={!canSubmit}>
        {submitting ? "Starting trial…" : "Start Trial"}
      </button>
    </form>
  );
}
