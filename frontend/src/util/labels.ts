import type { DeliveryKind, LedgerEventType, PayoutStatus } from "../api/types";
import type { BadgeTone } from "../components/StatusBadge";

export const DELIVERY_KIND_LABEL: Record<DeliveryKind, string> = {
  PROCUREMENT: "Procurement",
  CREDIT_NOTE: "Credit note",
  DEBIT_NOTE: "Debit note",
};

export const PAYOUT_STATUS_LABEL: Record<PayoutStatus, string> = {
  DRAFT: "Draft",
  FINALISED: "Finalised",
  PAID: "Paid",
};

export const LEDGER_EVENT_LABEL: Record<LedgerEventType, string> = {
  DELIVERY: "Delivery",
  CORRECTION: "Correction",
  ADVANCE: "Advance",
  PAYOUT: "Payout",
};

export function deliveryKindTone(kind: DeliveryKind): BadgeTone {
  if (kind === "CREDIT_NOTE") return "credit";
  if (kind === "DEBIT_NOTE") return "debit";
  return "procurement";
}

export function payoutStatusTone(status: PayoutStatus): BadgeTone {
  if (status === "DRAFT") return "draft";
  if (status === "FINALISED") return "finalised";
  return "paid";
}
