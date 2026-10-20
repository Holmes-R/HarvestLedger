// Pure helpers for the payout screen. Nothing here performs advance recovery or
// any other financial arithmetic: the API owns `advance_deduction`, `net_amount`
// and the recovery rule. These helpers only classify stored state, describe the
// documented policy and shape display copy.

import type { Payout, PayoutGeneration, PayoutStatus } from "../api/types";
import { formatMoney } from "./decimal";

/** A DRAFT has not recovered anything yet; the API stores `0.00` and net=gross. */
export const DRAFT_ADVANCE_NOTE =
  "A Draft has not reduced the farmer's outstanding advance. The advance is recovered once, by the server, when the statement is finalised.";

/**
 * Zero or negative money, decided from the decimal string without parsing it.
 * The API pays such statements as-is (recovery is zero for a non-positive
 * gross), so the UI explains rather than blocks.
 */
export function isNonPositiveMoney(value: string | null | undefined): boolean {
  if (value === null || value === undefined) return false;
  const trimmed = value.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith("-")) return true;
  return /^0*(?:\.0+)?$/.test(trimmed);
}

export type PayoutAction = "finalise" | "mark-paid";

export interface PayoutActions {
  canFinalise: boolean;
  canMarkPaid: boolean;
  readOnlyReason: string | null;
}

/** Only a DRAFT may be finalised; only a FINALISED statement may be marked paid. */
export function payoutActions(status: PayoutStatus): PayoutActions {
  if (status === "DRAFT") {
    return { canFinalise: true, canMarkPaid: false, readOnlyReason: null };
  }
  if (status === "FINALISED") {
    return { canFinalise: false, canMarkPaid: true, readOnlyReason: null };
  }
  return {
    canFinalise: false,
    canMarkPaid: false,
    readOnlyReason:
      "This statement is paid. Its stored breakdown, recovery and timestamps are read-only; later corrections need a supplementary payout.",
  };
}

/** Same farmer/week statements other than `payout`, oldest first (by id). */
export function sameWeekStatements(
  payout: Payout,
  statements: readonly Payout[],
): Payout[] {
  return statements
    .filter(
      (candidate) =>
        candidate.id !== payout.id &&
        candidate.farmer === payout.farmer &&
        candidate.week_start === payout.week_start,
    )
    .sort((a, b) => a.id - b.id);
}

/** True when an earlier statement for the same farmer/week already exists. */
export function isSupplementary(
  payout: Payout,
  statements: readonly Payout[],
): boolean {
  return sameWeekStatements(payout, statements).some(
    (candidate) => candidate.id < payout.id,
  );
}

export type GenerationOutcome =
  | { kind: "draft"; payout: Payout }
  | { kind: "empty"; reason: string | null };

/** Decode the documented `{payout, reason}` envelope (201 draft / 200 empty). */
export function classifyGeneration(result: PayoutGeneration): GenerationOutcome {
  return result.payout
    ? { kind: "draft", payout: result.payout }
    : { kind: "empty", reason: result.reason };
}

export function generateEmptyMessage(reason: string | null): string {
  if (reason === "NO_ELIGIBLE_DELIVERIES") {
    return "No eligible deliveries in this week — nothing was generated and no balance changed.";
  }
  return `Nothing was generated${reason ? ` (${reason})` : ""}; no balance changed.`;
}

/** A 409 means the statement moved on (already finalised/paid) or changed. */
export function isPayoutStateConflict(error: {
  status: number;
  code: string;
}): boolean {
  return error.status === 409 && error.code === "payout_state_error";
}

export function finaliseConfirmation(payout: Payout): string {
  return `Finalise statement #${payout.id} for ${payout.farmer_name}, week ${payout.week_start} to ${payout.week_end} (Monday–Sunday)? Gross ${formatMoney(payout.gross_amount)}. Finalising freezes the statement and applies the advance recovery the server calculates once; it cannot be undone.`;
}

export function markPaidConfirmation(payout: Payout): string {
  return `Mark statement #${payout.id} for ${payout.farmer_name} (${payout.week_start} to ${payout.week_end}) as paid? Net payable ${formatMoney(payout.net_amount)}. This records the money as handed over, is final, and does not recover the advance again.`;
}

/** Explain a zero/negative statement using the API's documented policy. */
export function nonPositiveNote(payout: Payout): string | null {
  if (payout.status === "DRAFT") {
    return isNonPositiveMoney(payout.gross_amount)
      ? "This draft's gross is zero or negative. The API applies no advance recovery to a non-positive gross and the statement is payable as-is."
      : null;
  }
  return isNonPositiveMoney(payout.net_amount)
    ? "This statement's net is zero or negative. The API pays it as-is; no advance recovery applies to a non-positive gross."
    : null;
}
