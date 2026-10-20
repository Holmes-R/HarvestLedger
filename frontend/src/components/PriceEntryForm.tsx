import { useMemo, useState, type FormEvent } from "react";

import { toApiError, type ApiError } from "../api/client";
import { createPriceEntry } from "../api/endpoints";
import type { CropGrade, PriceListEntry } from "../api/types";
import { isApiDate, istToday } from "../util/dates";
import {
  classifyEffectiveDate,
  effectiveDateNote,
  gradeOptionsFromGrades,
  cropOptionsFromGrades,
  priceConflict,
  validatePriceEntry,
  type PriceConflict,
} from "../util/pricing";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DecimalInput, Field, Select, TextInput } from "./form";

export interface PriceEntryFormProps {
  /** Every grade (all pages); `undefined` while the reference data loads. */
  grades: Map<number, CropGrade> | undefined;
  onSaved: (entry: PriceListEntry) => void;
}

/**
 * Append a single effective-dated price. There is deliberately no edit or delete
 * control: history is immutable, so a mistake is corrected by appending another
 * entry with a different effective date.
 */
export function PriceEntryForm({ grades, onSaved }: PriceEntryFormProps) {
  const [cropId, setCropId] = useState("");
  const [gradeId, setGradeId] = useState("");
  const [price, setPrice] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(istToday());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [conflict, setConflict] = useState<PriceConflict | null>(null);

  const cropOptions = useMemo(() => cropOptionsFromGrades(grades), [grades]);
  const gradeOptions = useMemo(
    () => gradeOptionsFromGrades(grades, cropId),
    [grades, cropId],
  );

  const validation = validatePriceEntry({ cropId, gradeId, price, effectiveFrom });
  const timing = isApiDate(effectiveFrom)
    ? classifyEffectiveDate(effectiveFrom, istToday())
    : null;

  function changeCrop(value: string) {
    setCropId(value);
    setGradeId("");
    setConflict(null);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validation.valid || busy) return;
    setError(undefined);
    setConflict(null);
    setBusy(true);
    try {
      const saved = await createPriceEntry({
        crop: Number(cropId),
        grade: Number(gradeId),
        price_per_kg: price.trim(),
        effective_from: effectiveFrom,
      });
      // Keep crop/grade/date so adding another date for the same grade is quick.
      setPrice("");
      onSaved(saved);
    } catch (cause) {
      const apiError = toApiError(cause);
      const mapped = priceConflict(apiError);
      if (mapped) setConflict(mapped);
      else setError(apiError);
    } finally {
      setBusy(false);
    }
  }

  const gradeError =
    conflict?.field === "grade" ? conflict.message : validation.grade;
  const dateError = conflict?.field === "date" ? conflict.message : validation.date;

  return (
    <form className="form" onSubmit={onSubmit} noValidate>
      <ErrorBanner error={error} />
      {conflict ? (
        <div className="banner banner-warning" role="alert">
          <strong>Not added.</strong> Fix the highlighted field and try again —
          existing entries are never overwritten.
        </div>
      ) : null}

      <div className="form-row">
        <Field label="Crop" htmlFor="p-crop" error={validation.crop}>
          <Select
            id="p-crop"
            value={cropId}
            onChange={changeCrop}
            placeholder="Select a crop…"
            options={cropOptions}
            disabled={!grades}
          />
        </Field>
        <Field label="Grade" htmlFor="p-grade" error={gradeError}>
          <Select
            id="p-grade"
            value={gradeId}
            onChange={(value) => {
              setGradeId(value);
              setConflict(null);
            }}
            placeholder={cropId ? "Select…" : "Pick a crop first"}
            disabled={!grades || !cropId}
            options={gradeOptions}
          />
        </Field>
        <Field
          label="Rate (₹/kg)"
          htmlFor="p-price"
          error={validation.price}
          hint="Stored exactly as entered, up to 2 decimal places."
        >
          <DecimalInput
            id="p-price"
            value={price}
            onChange={setPrice}
            places={2}
            placeholder="24.50"
          />
        </Field>
        <Field label="Effective from" htmlFor="p-from" error={dateError}>
          <TextInput
            id="p-from"
            type="date"
            value={effectiveFrom}
            onChange={setEffectiveFrom}
          />
        </Field>
      </div>

      <div className="form-actions">
        <Button
          type="submit"
          disabled={!validation.valid || !grades}
          pending={busy}
          pendingLabel="Adding…"
        >
          Add price
        </Button>
      </div>

      <p className="help" role="status" aria-live="polite">
        {timing
          ? effectiveDateNote(timing)
          : "Choose an effective date to see how it applies."}
      </p>
    </form>
  );
}
