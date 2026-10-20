import type {
  LedgerDelivery,
  LedgerEvent,
  LedgerPayout,
  LedgerSummary,
} from "../api/types";
import type { BadgeTone } from "../components/StatusBadge";
import { formatMoney } from "./decimal";
import { payoutStatusTone } from "./labels";

export const LEDGER_PAGE_SIZE = 20;

export const LEDGER_SCOPE_NOTE =
  "The summary covers the whole account. Paging or date filters only change the events listed below; they never change the balance or totals.";

export const NO_DOUBLE_COUNT_NOTE =
  "A payout is not extra income. Each delivery is counted once: settled earnings add up finalised or paid payout gross totals, and their member deliveries are not added again.";

export const RECOVERY_POLICY_NOTE =
  "An advance is recovered once, when a payout is finalised. Marking that payout paid does not recover it again.";

export const RECONCILIATION_HINT =
  "The stored outstanding advance is checked against every advance minus all recoveries from finalised or paid payouts.";

export function isLedgerFiltered(
  from: string,
  to: string,
  eventType: string,
): boolean {
  return Boolean(from || to || eventType);
}

export function ledgerEmptyMessage(filtered: boolean): string {
  return filtered
    ? "No ledger events match this date window and event type."
    : "No ledger activity yet. Advances, deliveries, corrections and payouts will appear here.";
}

export function ledgerEventTone(event: LedgerEvent): BadgeTone {
  if (event.event_type === "ADVANCE") return "warn";
  if (event.event_type === "PAYOUT") {
    return event.payout ? payoutStatusTone(event.payout.status) : "paid";
  }
  if (event.event_type === "CORRECTION") {
    return event.delivery?.kind === "DEBIT_NOTE" ? "debit" : "credit";
  }
  return "procurement";
}

export function ledgerEventTitle(event: LedgerEvent): string {
  if (event.event_type === "ADVANCE") return `Advance #${event.id}`;
  if (event.event_type === "PAYOUT") return `Payout #${event.id}`;
  if (event.event_type === "CORRECTION") {
    const label =
      event.delivery?.kind === "DEBIT_NOTE" ? "Debit note" : "Credit note";
    return `${label} #${event.id}`;
  }
  return `Delivery #${event.id}`;
}

export function ledgerAmountMeaning(event: LedgerEvent): string {
  if (event.event_type === "ADVANCE") return "Advance given";
  if (event.event_type === "PAYOUT") {
    return event.payout?.is_draft ? "Draft net (projection)" : "Net payable";
  }
  if (event.event_type === "CORRECTION") {
    return event.delivery?.kind === "DEBIT_NOTE"
      ? "Debit from farmer"
      : "Credit to farmer";
  }
  return "Earning";
}

export function ledgerPayoutStateNote(payout: LedgerPayout): string {
  if (payout.is_draft) {
    return "Draft projection - recovery not yet applied.";
  }
  if (payout.status === "FINALISED") {
    return "Recovery applied once at finalisation. Marking paid will not recover it again.";
  }
  return "Paid. Recovery was applied once at finalisation, not again when paid.";
}

export function ledgerDeliveryPayoutLabel(
  delivery: LedgerDelivery,
): string | null {
  return delivery.is_assigned
    ? `In payout #${delivery.payout}`
    : "Not in a payout yet";
}

export function payoutArithmeticWarnings(payout: LedgerPayout): string[] {
  const warnings: string[] = [];
  if (!payout.gross_matches_members) {
    warnings.push("Stored gross does not match its member lines.");
  }
  if (!payout.net_equals_gross_minus_deduction) {
    warnings.push("Stored net does not equal gross minus recovery.");
  }
  return warnings;
}

export function earningsIdentityText(summary: LedgerSummary): string {
  return [
    `Settled ${formatMoney(summary.settled_earnings)}`,
    `Draft ${formatMoney(summary.draft_projection)}`,
    `Unassigned ${formatMoney(summary.unassigned_earnings)}`,
    `= ${formatMoney(summary.total_recorded_amount)} recorded`,
  ].join(" + ").replace(" + = ", " = ");
}

export function ledgerContextLink(
  section: "deliveries" | "payouts",
  id: number,
  farmerId: string | number,
): string {
  const farmer = encodeURIComponent(String(farmerId));
  return `#/${section}/${id}?from=ledger&farmer=${farmer}`;
}

export function ledgerContextSuffix(params: URLSearchParams): string {
  const from = params.get("from");
  const farmer = params.get("farmer");
  if (from !== "ledger" || !farmer) return "";
  return `?from=ledger&farmer=${encodeURIComponent(farmer)}`;
}

export function ledgerBackTarget(params: URLSearchParams): string | null {
  const suffix = ledgerContextSuffix(params);
  return suffix ? `#/ledger${suffix}` : null;
}
