// Pure helpers for the price-history screen. The price list is append-only: it
// has no update/delete path, so these helpers only validate new entries, explain
// how an effective date behaves, and translate the append-only conflict into
// guidance. Kept free of React and network calls so they can be tested directly.

import type { ApiError } from "../api/client";
import type { CropGrade } from "../api/types";
import { validateDecimal } from "./decimal";
import { isApiDate } from "./dates";

/** Newest effective date first; the API completes this with an `id` tie-breaker. */
export const PRICE_ORDERING = "-effective_from";

export interface PriceEntryInput {
  cropId: string;
  gradeId: string;
  price: string;
  effectiveFrom: string;
}

export interface PriceEntryValidation {
  crop: string | null;
  grade: string | null;
  price: string | null;
  date: string | null;
  valid: boolean;
}

/**
 * Validate the four inputs of a new price entry. The rate must be a decimal with
 * at most 2 places (excess precision is rejected here and again by the API) and
 * strictly positive; the effective date must be a real `YYYY-MM-DD` calendar
 * date. Back-dated, current and future dates are all valid.
 */
export function validatePriceEntry(input: PriceEntryInput): PriceEntryValidation {
  const crop = input.cropId ? null : "Select a crop.";
  const grade = input.gradeId ? null : "Select a grade.";
  const price = input.price.trim()
    ? validateDecimal(input.price, { places: 2, positive: true })
    : "Required.";
  const date = !input.effectiveFrom
    ? "Select an effective date."
    : isApiDate(input.effectiveFrom)
      ? null
      : "Enter a valid date (YYYY-MM-DD).";
  return { crop, grade, price, date, valid: !crop && !grade && !price && !date };
}

export type EffectiveTiming = "past" | "today" | "future";

/** Classify an effective date against the current IST business date. */
export function classifyEffectiveDate(
  effectiveFrom: string,
  today: string,
): EffectiveTiming {
  if (effectiveFrom < today) return "past";
  if (effectiveFrom > today) return "future";
  return "today";
}

/** Plain-language note about what an effective date does (and does not) change. */
export function effectiveDateNote(timing: EffectiveTiming): string {
  switch (timing) {
    case "past":
      return "Back-dated: appended to history. It never overwrites an existing entry, and deliveries already recorded keep the price they were saved with.";
    case "future":
      return "Future-dated: it prices deliveries on or after this date only. Deliveries recorded before then are unaffected.";
    default:
      return "Effective from today: it prices deliveries recorded on or after today.";
  }
}

export interface PriceConflict {
  field: "grade" | "date";
  message: string;
}

/**
 * Translate the append-only API conflicts into a field error. A duplicate
 * `(grade, effective date)` is never overwritten, so the remedy is a different
 * date, not an edit.
 */
export function priceConflict(error: ApiError): PriceConflict | null {
  if (error.code === "price_already_exists") {
    return {
      field: "date",
      message:
        "A price for this grade already exists on that effective date. History is append-only — choose a different date instead of overwriting it.",
    };
  }
  if (error.code === "grade_not_allowed") {
    return {
      field: "grade",
      message: "That grade is not allowed for the selected crop.",
    };
  }
  return null;
}

/** Crop options derived from every grade, so no crop is hidden by pagination. */
export function cropOptionsFromGrades(
  grades: Map<number, CropGrade> | undefined,
): Array<{ value: string; label: string }> {
  const crops = new Map<number, string>();
  grades?.forEach((grade) => crops.set(grade.crop, grade.crop_name));
  return [...crops.entries()]
    .map(([id, name]) => ({ value: String(id), label: name }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Grade options for a crop (all grades when `cropId` is empty). */
export function gradeOptionsFromGrades(
  grades: Map<number, CropGrade> | undefined,
  cropId: string,
): Array<{ value: string; label: string }> {
  return grades
    ? [...grades.values()]
        .filter((grade) => !cropId || String(grade.crop) === cropId)
        .map((grade) => ({
          value: String(grade.id),
          label: cropId ? grade.code : `${grade.crop_name} · ${grade.code}`,
        }))
        .sort((a, b) => a.label.localeCompare(b.label))
    : [];
}
