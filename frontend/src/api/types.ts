// Types mirror the actual M3 API responses (verified against live responses and
// the generated OpenAPI schema). Every decimal is a *string* at the column's
// scale; dates are `YYYY-MM-DD`; timestamps are ISO-8601 with a +05:30 offset
// (rendered in the business timezone, not `Z`). Never coerce money to `number`.

export type DeliveryKind = "PROCUREMENT" | "CREDIT_NOTE" | "DEBIT_NOTE";
export type GradeNoteKind = "CREDIT_NOTE" | "DEBIT_NOTE";
export type PayoutStatus = "DRAFT" | "FINALISED" | "PAID";
export type LedgerEventType = "DELIVERY" | "CORRECTION" | "ADVANCE" | "PAYOUT";

export const DELIVERY_KINDS: readonly DeliveryKind[] = [
  "PROCUREMENT",
  "CREDIT_NOTE",
  "DEBIT_NOTE",
];
export const GRADE_NOTE_KINDS: readonly GradeNoteKind[] = [
  "CREDIT_NOTE",
  "DEBIT_NOTE",
];
export const PAYOUT_STATUSES: readonly PayoutStatus[] = [
  "DRAFT",
  "FINALISED",
  "PAID",
];
export const LEDGER_EVENT_TYPES: readonly LedgerEventType[] = [
  "DELIVERY",
  "CORRECTION",
  "ADVANCE",
  "PAYOUT",
];

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Farmer {
  id: number;
  name: string;
  phone: string;
  village: string;
  bank_reference: string;
  outstanding_advance: string;
  created_at: string;
}

export interface CropGradeRef {
  id: number;
  code: string;
}

export interface Crop {
  id: number;
  name: string;
  moisture_threshold: string;
  max_moisture: string;
  allowed_grades: CropGradeRef[];
  created_at: string;
}

export interface CropGrade {
  id: number;
  crop: number;
  crop_name: string;
  code: string;
  created_at: string;
}

export interface PriceListEntry {
  id: number;
  crop_grade: number;
  crop_grade_code: string;
  crop: number;
  crop_name: string;
  price_per_kg: string;
  effective_from: string;
  created_at: string;
}

export interface Delivery {
  id: number;
  farmer: number;
  kind: DeliveryKind;
  crop_grade: number | null;
  delivered_on: string | null;
  accounting_date: string | null;
  gross_weight_kg: string | null;
  moisture_percent: string | null;
  threshold_used: string | null;
  deduction_percent: string;
  deduction_kg: string;
  net_kg: string;
  applied_price: string | null;
  price_list_entry: number | null;
  amount: string | null;
  calculation_version: number;
  original_delivery: number | null;
  correction_magnitude: string | null;
  reason: string;
  payout: number | null;
  recorded_at: string;
}

export interface DeliveryPreview {
  farmer_id: number;
  crop_grade: number;
  delivered_on: string;
  accounting_date: string;
  business_date: string;
  gross_weight_kg: string;
  moisture_percent: string;
  threshold_used: string;
  applied_price: string;
  price_list_entry: number;
  deduction_percent: string;
  deduction_kg: string;
  net_kg: string;
  amount: string;
}

export interface Correction {
  id: number;
  farmer: number;
  kind: GradeNoteKind;
  original_delivery: number | null;
  correction_magnitude: string;
  reason: string;
  accounting_date: string | null;
  amount: string;
  payout: number | null;
  recorded_at: string;
}

export interface Advance {
  id: number;
  farmer: number;
  amount: string;
  given_on: string;
  created_at: string;
}

export interface Payout {
  id: number;
  farmer: number;
  farmer_name: string;
  week_start: string;
  week_end: string;
  status: PayoutStatus;
  gross_amount: string;
  advance_deduction: string;
  net_amount: string;
  deliveries: Delivery[];
  created_at: string;
  finalised_at: string | null;
  paid_at: string | null;
}

export interface PayoutGeneration {
  payout: Payout | null;
  reason: string | null;
}

export interface Reconciliation {
  farmer_id: number;
  total_advances: string;
  total_recovered: string;
  expected_outstanding: string;
  stored_outstanding: string;
  difference: string;
  is_reconciled: boolean;
}

export interface LedgerSummary {
  farmer_id: number;
  name: string;
  phone: string;
  outstanding_advance: string;
  reconciliation: Reconciliation;
  total_advances: string;
  settled_earnings: string;
  total_recovered: string;
  draft_projection: string;
  unassigned_earnings: string;
  total_recorded_amount: string;
  earnings_identity_holds: boolean;
  is_reconciled: boolean;
  history_from: string | null;
  history_to: string | null;
}

export interface LedgerDelivery {
  id: number;
  kind: DeliveryKind;
  crop_grade: number | null;
  delivered_on: string | null;
  accounting_date: string | null;
  gross_weight_kg: string | null;
  moisture_percent: string | null;
  net_kg: string | null;
  applied_price: string | null;
  amount: string | null;
  payout: number | null;
  original_delivery: number | null;
  correction_magnitude: string | null;
  reason: string;
  is_correction: boolean;
  is_assigned: boolean;
  signed_amount: string;
}

export interface LedgerAdvance {
  id: number;
  amount: string;
  given_on: string;
  created_at: string;
}

export interface LedgerPayout {
  id: number;
  week_start: string;
  week_end: string;
  status: PayoutStatus;
  gross_amount: string;
  advance_deduction: string;
  net_amount: string;
  finalised_at: string | null;
  paid_at: string | null;
  delivery_ids: number[];
  member_total: string;
  is_draft: boolean;
  is_settled: boolean;
  gross_matches_members: boolean;
  net_equals_gross_minus_deduction: boolean;
}

export interface LedgerEvent {
  event_type: LedgerEventType;
  id: number;
  date: string;
  amount: string;
  delivery: LedgerDelivery | null;
  advance: LedgerAdvance | null;
  payout: LedgerPayout | null;
}

export interface LedgerPage {
  count: number;
  next: string | null;
  previous: string | null;
  summary: LedgerSummary;
  results: LedgerEvent[];
}

// --- Request payloads -------------------------------------------------------

export interface FarmerWrite {
  name: string;
  phone: string;
  village: string;
  bank_reference?: string;
}

export interface CropWrite {
  name: string;
  moisture_threshold: string;
  max_moisture: string;
  allowed_grades?: string[];
}

export interface PriceEntryWrite {
  crop: number;
  grade: number | string;
  price_per_kg: string;
  effective_from: string;
}

export interface DeliveryWrite {
  farmer: number;
  crop_grade: number;
  delivered_on: string;
  gross_weight_kg: string;
  moisture_percent: string;
}

export type DeliveryEdit = Partial<Omit<DeliveryWrite, "farmer">>;

export interface AdvanceWrite {
  farmer: number;
  amount: string;
  given_on: string;
}

export interface CorrectionWrite {
  original_delivery: number;
  kind: GradeNoteKind;
  magnitude: string;
  reason: string;
}

export interface DeliveryCorrectionWrite {
  kind: GradeNoteKind;
  magnitude: string;
  reason: string;
}

export interface PayoutGenerateWrite {
  farmer: number;
  week_start: string;
}
