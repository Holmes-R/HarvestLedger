// Pure helpers for the delivery screen: input validation, grade/crop matching,
// preview-vs-stored comparison and edit lock reasons. Kept free of React and
// network calls so they can be tested directly.

import type { Delivery, DeliveryPreview, PayoutStatus } from "../api/types";
import { formatAmount, validateDecimal } from "./decimal";
import { isApiDate } from "./dates";

export interface DeliveryInput {
  farmerId: string;
  cropId: string;
  gradeId: string;
  deliveredOn: string;
  gross: string;
  moisture: string;
}

export interface DeliveryValidation {
  farmer: string | null;
  crop: string | null;
  grade: string | null;
  date: string | null;
  gross: string | null;
  moisture: string | null;
  valid: boolean;
}

/** Validate the six inputs. Decimals stay strings; only their shape is checked. */
export function validateDeliveryInputs(input: DeliveryInput): DeliveryValidation {
  const farmer = input.farmerId ? null : "Select a farmer.";
  const crop = input.cropId ? null : "Select a crop.";
  const grade = input.gradeId ? null : "Select a grade.";
  const date = !input.deliveredOn
    ? "Select a delivery date."
    : isApiDate(input.deliveredOn)
      ? null
      : "Enter a valid date (YYYY-MM-DD).";
  const gross = input.gross.trim()
    ? validateDecimal(input.gross, { places: 3, positive: true })
    : "Required.";
  const moisture = input.moisture.trim()
    ? validateDecimal(input.moisture, { places: 2, positive: true })
    : "Required.";

  return {
    farmer,
    crop,
    grade,
    date,
    gross,
    moisture,
    valid: !farmer && !crop && !grade && !date && !gross && !moisture,
  };
}

/** True when the selected grade belongs to the selected crop. */
export function gradeBelongsToCrop(
  grade: { crop: number } | undefined,
  cropId: string,
): boolean {
  return Boolean(grade && cropId && String(grade.crop) === cropId);
}

export interface DeliveryFieldComparison {
  key: string;
  label: string;
  preview: string | null;
  stored: string | null;
  changed: boolean;
}

export interface DeliveryComparison {
  changed: boolean;
  fields: DeliveryFieldComparison[];
  /** Stored amount minus preview amount, e.g. `+₹2.50`; null if unparseable. */
  amountDelta: string | null;
}

const COMPARED_FIELDS: ReadonlyArray<{
  key: string;
  label: string;
  pick: (value: DeliveryPreview | Delivery) => string | null;
}> = [
  {
    key: "applied_price",
    label: "Applied price",
    pick: (value) => value.applied_price ?? null,
  },
  {
    key: "price_list_entry",
    label: "Price entry",
    pick: (value) => (value.price_list_entry != null ? `#${value.price_list_entry}` : null),
  },
  {
    key: "deduction_percent",
    label: "Deduction %",
    pick: (value) => value.deduction_percent ?? null,
  },
  {
    key: "deduction_kg",
    label: "Deduction kg",
    pick: (value) => value.deduction_kg ?? null,
  },
  { key: "net_kg", label: "Net kg", pick: (value) => value.net_kg ?? null },
  { key: "amount", label: "Amount", pick: (value) => value.amount ?? null },
  {
    key: "accounting_date",
    label: "Accounting date",
    pick: (value) => value.accounting_date ?? null,
  },
];

function minorUnits(value: string | null | undefined): bigint | null {
  if (value === null || value === undefined || value === "") return null;
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match) return null;
  const sign = match[1] === "-" ? -1n : 1n;
  const fraction = (match[3] ?? "").padEnd(2, "0");
  return sign * (BigInt(match[2]) * 100n + BigInt(fraction));
}

/**
 * Money difference between two decimal strings, computed in minor units with
 * `BigInt` so no float is involved. This is display-only: it is never sent back
 * to the API.
 */
export function moneyDelta(
  from: string | null | undefined,
  to: string | null | undefined,
): string | null {
  const start = minorUnits(from);
  const end = minorUnits(to);
  if (start === null || end === null) return null;
  const delta = end - start;
  const sign = delta > 0n ? "+" : delta < 0n ? "-" : "";
  const absolute = delta < 0n ? -delta : delta;
  const whole = absolute / 100n;
  const fraction = (absolute % 100n).toString().padStart(2, "0");
  return `${sign}\u20B9${formatAmount(whole.toString())}.${fraction}`;
}

/** Compare the authoritative stored delivery with the earlier preview. */
export function comparePreviewToStored(
  preview: DeliveryPreview,
  stored: Delivery,
): DeliveryComparison {
  const fields = COMPARED_FIELDS.map(({ key, label, pick }) => {
    const before = pick(preview);
    const after = pick(stored);
    return { key, label, preview: before, stored: after, changed: before !== after };
  });
  return {
    changed: fields.some((field) => field.changed),
    fields,
    amountDelta: moneyDelta(preview.amount, stored.amount),
  };
}

/**
 * Why a delivery cannot be edited, or `null` when it can. Corrections are
 * immutable; a delivery in a FINALISED/PAID statement is locked (the API returns
 * 409) and must be adjusted with a correction instead.
 */
export function deliveryLockReason(
  delivery: Pick<Delivery, "kind" | "payout">,
  payoutStatus?: PayoutStatus,
): string | null {
  if (delivery.kind !== "PROCUREMENT") {
    return "Correction notes are immutable. Record another note instead.";
  }
  if (payoutStatus === "FINALISED" || payoutStatus === "PAID") {
    return `This delivery is locked in a ${payoutStatus.toLowerCase()} payout. Finalised statements are immutable — record a correction instead.`;
  }
  return null;
}
