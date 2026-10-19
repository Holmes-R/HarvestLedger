// Typed functions for every M3 operation the UI uses. Paths and shapes mirror
// the actual API (22 routes under /api/v1/); nothing is inferred from an
// earlier proposal. Every function accepts `RequestOptions` so callers can pass
// an `AbortSignal` (and an explicit request id) through to the client. Request
// bodies carry only API-accepted input fields — decimal strings stay strings and
// dates are serialised to `YYYY-MM-DD` via `toApiDate`.

import { api, type QueryValue, type RequestOptions } from "./client";
import { toApiDate } from "../util/dates";
import type {
  Advance,
  AdvanceWrite,
  Correction,
  CorrectionWrite,
  Crop,
  CropGrade,
  CropWrite,
  Delivery,
  DeliveryCorrectionWrite,
  DeliveryEdit,
  DeliveryPreview,
  DeliveryWrite,
  Farmer,
  FarmerWrite,
  LedgerPage,
  Payout,
  PayoutGenerateWrite,
  PayoutGeneration,
  PriceEntryWrite,
  PriceListEntry,
  Reconciliation as AdvanceReconciliation,
} from "./types";

type Q = Record<string, QueryValue>;

export const health = (options?: RequestOptions) =>
  api.get<{ status: string }>("/health/", undefined, options);

// --- Farmers ----------------------------------------------------------------
export const listFarmers = (query: Q = {}, options?: RequestOptions) =>
  api.page<Farmer>("/farmers/", query, options);
export const getFarmer = (id: number, options?: RequestOptions) =>
  api.get<Farmer>(`/farmers/${id}/`, undefined, options);
export const createFarmer = (body: FarmerWrite, options?: RequestOptions) =>
  api.post<Farmer>("/farmers/", body, options);
export const updateFarmer = (id: number, body: FarmerWrite, options?: RequestOptions) =>
  api.patch<Farmer>(`/farmers/${id}/`, body, options);
export const getAdvanceReconciliation = (farmerId: number, options?: RequestOptions) =>
  api.get<AdvanceReconciliation>(`/farmers/${farmerId}/advance-reconciliation/`, undefined, options);

// --- Crops / grades ---------------------------------------------------------
export const listCrops = (query: Q = {}, options?: RequestOptions) =>
  api.page<Crop>("/crops/", query, options);
export const getCrop = (id: number, options?: RequestOptions) =>
  api.get<Crop>(`/crops/${id}/`, undefined, options);
export const createCrop = (body: CropWrite, options?: RequestOptions) =>
  api.post<Crop>("/crops/", body, options);
export const updateCrop = (id: number, body: CropWrite, options?: RequestOptions) =>
  api.patch<Crop>(`/crops/${id}/`, body, options);
export const listGrades = (query: Q = {}, options?: RequestOptions) =>
  api.page<CropGrade>("/grades/", query, options);

// --- Prices -----------------------------------------------------------------
export const listPrices = (query: Q = {}, options?: RequestOptions) =>
  api.page<PriceListEntry>("/price-lists/", query, options);
export const createPriceEntry = (body: PriceEntryWrite, options?: RequestOptions) =>
  api.post<PriceListEntry>(
    "/price-lists/",
    { ...body, effective_from: toApiDate(body.effective_from) },
    options,
  );

// --- Deliveries -------------------------------------------------------------
function serializeDeliveryWrite(body: DeliveryWrite): DeliveryWrite {
  return { ...body, delivered_on: toApiDate(body.delivered_on) };
}

function serializeDeliveryEdit(body: DeliveryEdit): DeliveryEdit {
  return body.delivered_on === undefined
    ? body
    : { ...body, delivered_on: toApiDate(body.delivered_on) };
}

export const previewDelivery = (body: DeliveryWrite, options?: RequestOptions) =>
  api.post<DeliveryPreview>("/deliveries/preview/", serializeDeliveryWrite(body), options);
export const listDeliveries = (query: Q = {}, options?: RequestOptions) =>
  api.page<Delivery>("/deliveries/", query, options);
export const createDelivery = (body: DeliveryWrite, options?: RequestOptions) =>
  api.post<Delivery>("/deliveries/", serializeDeliveryWrite(body), options);
export const getDelivery = (id: number, options?: RequestOptions) =>
  api.get<Delivery>(`/deliveries/${id}/`, undefined, options);
export const editDelivery = (id: number, body: DeliveryEdit, options?: RequestOptions) =>
  api.patch<Delivery>(`/deliveries/${id}/`, serializeDeliveryEdit(body), options);

// --- Corrections ------------------------------------------------------------
export const listCorrections = (query: Q = {}, options?: RequestOptions) =>
  api.page<Correction>("/corrections/", query, options);
export const createCorrection = (body: CorrectionWrite, options?: RequestOptions) =>
  api.post<Correction>("/corrections/", body, options);
export const createDeliveryCorrection = (
  deliveryId: number,
  body: DeliveryCorrectionWrite,
  options?: RequestOptions,
) => api.post<Correction>(`/deliveries/${deliveryId}/corrections/`, body, options);
export const getCorrection = (id: number, options?: RequestOptions) =>
  api.get<Correction>(`/corrections/${id}/`, undefined, options);

// --- Advances ---------------------------------------------------------------
export const listAdvances = (query: Q = {}, options?: RequestOptions) =>
  api.page<Advance>("/advances/", query, options);
export const createAdvance = (body: AdvanceWrite, options?: RequestOptions) =>
  api.post<Advance>("/advances/", { ...body, given_on: toApiDate(body.given_on) }, options);

// --- Payouts ----------------------------------------------------------------
export const generatePayout = (body: PayoutGenerateWrite, options?: RequestOptions) =>
  api.post<PayoutGeneration>(
    "/payouts/generate/",
    { ...body, week_start: toApiDate(body.week_start) },
    options,
  );
export const listPayouts = (query: Q = {}, options?: RequestOptions) =>
  api.page<Payout>("/payouts/", query, options);
export const getPayout = (id: number, options?: RequestOptions) =>
  api.get<Payout>(`/payouts/${id}/`, undefined, options);
export const finalisePayout = (id: number, options?: RequestOptions) =>
  api.post<Payout>(`/payouts/${id}/finalise/`, undefined, options);
export const markPayoutPaid = (id: number, options?: RequestOptions) =>
  api.post<Payout>(`/payouts/${id}/mark-paid/`, undefined, options);

// --- Farmer ledger ----------------------------------------------------------
export const getLedger = (farmerId: number, query: Q = {}, options?: RequestOptions) =>
  api.get<LedgerPage>(`/farmers/${farmerId}/ledger/`, query, options);
