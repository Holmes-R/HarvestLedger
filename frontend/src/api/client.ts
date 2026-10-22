// Shared typed API client for the HarvestLedger M3 API.
//
// Design notes:
// * Money, weights and percentages are never coerced. Response decimals stay
//   strings, and request builders only ever send the fields the API accepts as
//   input — never a server-computed financial value.
// * Every request carries an `X-Request-ID` (client-generated unless supplied),
//   so a browser log can be matched to the server's structured logs. The id is
//   preserved on success (via the optional callback) and on every error.
// * Writes are never retried automatically. A network failure, an abort or a 5xx
//   response leaves the outcome **unknown**, and the raised `ApiError` carries
//   enough state (method, path, request id, guidance) for the UI to re-fetch and
//   reconcile before deciding whether to retry.

import type { Page } from "./types";

export interface ApiErrorDetail {
  code: string;
  message: string;
}

export interface ApiErrorEnvelope {
  code: string;
  message: string;
  details: Record<string, ApiErrorDetail[]>;
  request_id: string;
}

/** How a failed request ended. "unknown" means it may have changed state. */
export type MutationOutcome = "rejected" | "unknown";

/** Stable client-side error codes; server codes arrive in the envelope. */
export const CLIENT_ERROR_CODES = {
  networkError: "network_error",
  requestAborted: "request_aborted",
  invalidUrl: "invalid_request_url",
  protectedPayload: "protected_payload",
  error: "error",
} as const;

/**
 * Fields the API computes and never accepts as input. Sending one is a client
 * bug, so the client refuses it locally instead of trusting it to the network.
 */
export const PROTECTED_WRITE_FIELDS: readonly string[] = [
  "amount",
  "net_kg",
  "deduction_kg",
  "deduction_percent",
  "applied_price",
  "threshold_used",
  "price_list_entry",
  "calculation_version",
  "accounting_date",
  "outstanding_advance",
  "payout",
  "gross_amount",
  "advance_deduction",
  "net_amount",
  "total_recovered",
  "farmer_name",
  "week_end",
  "signed_amount",
  "status",
  "deliveries",
  "created_at",
  "recorded_at",
  "finalised_at",
  "paid_at",
];

/**
 * Path-specific exceptions to {@link PROTECTED_WRITE_FIELDS}: a field that is
 * computed for one resource is legitimate input for another. `amount` is the
 * advance principal on `POST /advances/` but a server-computed total elsewhere.
 */
export const WRITABLE_FIELD_EXCEPTIONS: ReadonlyArray<{
  pattern: RegExp;
  fields: readonly string[];
}> = [{ pattern: /^\/advances\/?$/, fields: ["amount"] }];

/** Everything the UI needs to reconcile a failed (possibly applied) write. */
export interface Reconciliation {
  method: string;
  path: string;
  requestId: string;
  isWrite: boolean;
  outcome: MutationOutcome;
  /** True only when resending cannot double-apply a write. */
  safeToRetry: boolean;
  guidance: string;
}

export interface ApiErrorInit {
  status: number;
  code: string;
  message: string;
  details?: Record<string, ApiErrorDetail[]>;
  requestId?: string;
  method?: string;
  path?: string;
  isWrite?: boolean;
  outcome?: MutationOutcome;
}

function buildReconciliation(error: {
  method: string;
  path: string;
  requestId: string;
  isWrite: boolean;
  outcome: MutationOutcome;
}): Reconciliation {
  const { method, path, requestId, isWrite, outcome } = error;
  let guidance: string;
  if (outcome === "unknown" && isWrite) {
    guidance =
      "The server may or may not have applied this write. Re-fetch the affected collection or record and confirm whether it landed before retrying; do not assume the failure meant nothing was saved.";
  } else if (outcome === "unknown") {
    guidance = "The outcome is unknown. Re-fetch the resource before relying on it.";
  } else {
    guidance = "The server rejected the request; it was not applied. Correct the input and try again.";
  }
  return {
    method,
    path,
    requestId,
    isWrite,
    outcome,
    safeToRetry: !isWrite || outcome === "rejected",
    guidance,
  };
}

/** A failed request, decoded from the shared error envelope when present. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, ApiErrorDetail[]>;
  readonly requestId: string;
  readonly method: string;
  readonly path: string;
  readonly isWrite: boolean;
  readonly outcome: MutationOutcome;
  readonly reconciliation: Reconciliation;

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? {};
    this.requestId = init.requestId ?? "";
    this.method = init.method ?? "";
    this.path = init.path ?? "";
    this.isWrite = init.isWrite ?? false;
    this.outcome = init.outcome ?? "rejected";
    this.reconciliation = buildReconciliation(this);
  }

  /** Flatten `details` into `field: message` lines for display. */
  fieldMessages(): string[] {
    const lines: string[] = [];
    for (const [field, items] of Object.entries(this.details)) {
      for (const item of items) {
        lines.push(field === "detail" ? item.message : `${field}: ${item.message}`);
      }
    }
    return lines;
  }

  get isAborted(): boolean {
    return this.code === CLIENT_ERROR_CODES.requestAborted;
  }

  get isNetworkError(): boolean {
    return this.code === CLIENT_ERROR_CODES.networkError;
  }

  get isValidationError(): boolean {
    return this.status === 400 || this.status === 422;
  }

  /** True when the request may have changed server state. */
  get outcomeUnknown(): boolean {
    return this.outcome === "unknown";
  }
}

/** Normalise any thrown value into an `ApiError` for display. */
export function toApiError(cause: unknown): ApiError {
  if (cause instanceof ApiError) return cause;
  return new ApiError({
    status: 0,
    code: CLIENT_ERROR_CODES.error,
    message: cause instanceof Error ? cause.message : String(cause),
  });
}

/** True when a rejection came from an `AbortSignal` (safe to ignore in the UI). */
export function isAbortError(cause: unknown): boolean {
  if (cause instanceof ApiError) return cause.isAborted;
  if (cause instanceof DOMException) return cause.name === "AbortError";
  if (cause instanceof Error) return cause.name === "AbortError";
  return false;
}

const RAW_BASE = import.meta.env.VITE_API_BASE_URL;
export const API_BASE =
  (RAW_BASE && RAW_BASE.trim().replace(/\/+$/, "")) || "http://localhost:8000/api/v1";

// Demo-only reviewer clock. Held in memory only: the optional review key is
// never written to browser storage or any build-time VITE_* value.
let demoClock: string | null = null;
let demoReviewKey: string | null = null;

export interface DemoClockState {
  clock: string | null;
  reviewKey: string | null;
  enabled: boolean;
}

export function getDemoClock(): DemoClockState {
  return { clock: demoClock, reviewKey: demoReviewKey, enabled: Boolean(demoClock) };
}

export function setDemoClock(clock: string | null, reviewKey: string | null): void {
  demoClock = clock && clock.trim() ? clock.trim() : null;
  demoReviewKey = reviewKey && reviewKey.trim() ? reviewKey.trim() : null;
}

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  query?: Record<string, QueryValue>;
  body?: unknown;
  /** Cancel the request (the client raises a `request_aborted` error). */
  signal?: AbortSignal;
  /** Client request id; generated when omitted. */
  requestId?: string;
  /** Extra headers; merged over the defaults. */
  headers?: Record<string, string>;
  /** Called with the effective request id on success and on failure. */
  onRequestId?: (requestId: string) => void;
}

const REQUEST_ID_PATTERN = /^[A-Za-z0-9._:-]{8,128}$/;

/** A well-formed request id, matching the backend's acceptance rule. */
export function generateRequestId(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID().replace(/-/g, "");
  }
  const random = Math.random().toString(16).slice(2, 12);
  return `hl-${Date.now().toString(16)}-${random.padEnd(10, "0")}`;
}

function resolveUrl(pathOrUrl: string): URL {
  if (/^https?:\/\//i.test(pathOrUrl)) {
    const url = new URL(pathOrUrl);
    const base = new URL(API_BASE);
    const sameOrigin = url.origin === base.origin;
    const underBase = url.pathname.startsWith(base.pathname.replace(/\/$/, ""));
    if (!sameOrigin || !underBase) {
      throw new ApiError({
        status: 0,
        code: CLIENT_ERROR_CODES.invalidUrl,
        message: `Refusing to call ${url.origin}${url.pathname}; only ${API_BASE} is allowed.`,
      });
    }
    return url;
  }
  const path = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return new URL(API_BASE + path);
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = resolveUrl(path);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Refuse a write payload that carries a server-computed field. This is a safety
 * net: the API already rejects such fields (`400 protected_field`), but failing
 * locally makes the mistake obvious and keeps the value off the wire entirely.
 * `path` selects any per-resource exceptions (see {@link WRITABLE_FIELD_EXCEPTIONS}).
 */
export function assertWritablePayload(body: unknown, path = ""): void {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return;
  let forbidden: readonly string[] = PROTECTED_WRITE_FIELDS;
  for (const exception of WRITABLE_FIELD_EXCEPTIONS) {
    if (exception.pattern.test(path)) {
      forbidden = forbidden.filter((field) => !exception.fields.includes(field));
    }
  }
  const offending = Object.keys(body as Record<string, unknown>).filter((key) =>
    forbidden.includes(key),
  );
  if (offending.length > 0) {
    throw new ApiError({
      status: 0,
      code: CLIENT_ERROR_CODES.protectedPayload,
      message: `Refusing to send server-computed field(s): ${offending.join(", ")}.`,
      outcome: "rejected",
    });
  }
}

function isAbort(cause: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  if (cause instanceof DOMException) return cause.name === "AbortError";
  if (cause instanceof Error) return cause.name === "AbortError";
  return false;
}

function parseJson(text: string): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function readEnvelope(data: unknown): ApiErrorEnvelope | undefined {
  if (!data || typeof data !== "object") return undefined;
  const envelope = (data as { error?: unknown }).error;
  if (!envelope || typeof envelope !== "object") return undefined;
  const candidate = envelope as Partial<ApiErrorEnvelope>;
  if (typeof candidate.code !== "string" || typeof candidate.message !== "string") {
    return undefined;
  }
  return {
    code: candidate.code,
    message: candidate.message,
    details: candidate.details ?? {},
    request_id: candidate.request_id ?? "",
  };
}

export async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const upperMethod = method.toUpperCase();
  const isWrite = upperMethod !== "GET";
  if (isWrite) assertWritablePayload(options.body, path);

  const requestId = (options.requestId ?? generateRequestId()).trim();
  const sentRequestId = REQUEST_ID_PATTERN.test(requestId)
    ? requestId
    : generateRequestId();

  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  headers["X-Request-ID"] = sentRequestId;
  if (demoClock) headers["X-Test-Clock"] = demoClock;
  if (demoReviewKey) headers["X-Review-Key"] = demoReviewKey;
  if (options.headers) Object.assign(headers, options.headers);

  let url: string;
  try {
    url = buildUrl(path, options.query);
  } catch (cause) {
    throw toApiError(cause);
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: upperMethod,
      headers,
      signal: options.signal,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (cause) {
    const aborted = isAbort(cause, options.signal);
    const error = new ApiError({
      status: 0,
      code: aborted
        ? CLIENT_ERROR_CODES.requestAborted
        : CLIENT_ERROR_CODES.networkError,
      message: aborted
        ? "The request was cancelled before it completed."
        : "Could not reach the API. Is the backend running and VITE_API_BASE_URL correct?",
      requestId: sentRequestId,
      method: upperMethod,
      path,
      isWrite,
      // A dropped/aborted request may still have reached and changed the server.
      outcome: "unknown",
    });
    options.onRequestId?.(error.requestId);
    throw error;
  }

  const effectiveRequestId = response.headers.get("X-Request-ID") || sentRequestId;
  options.onRequestId?.(effectiveRequestId);

  const text = await response.text();
  const data = parseJson(text);

  if (!response.ok) {
    const envelope = readEnvelope(data);
    // A 5xx can come from a gateway after the write committed, so treat it as an
    // unknown write outcome; a 4xx is a definitive, rolled-back rejection.
    const outcome: MutationOutcome = response.status >= 500 ? "unknown" : "rejected";
    throw new ApiError({
      status: response.status,
      code: envelope?.code ?? CLIENT_ERROR_CODES.error,
      message:
        envelope?.message ||
        response.statusText ||
        `Request failed (${response.status}).`,
      details: envelope?.details,
      requestId: envelope?.request_id || effectiveRequestId,
      method: upperMethod,
      path,
      isWrite,
      outcome,
    });
  }

  return data as T;
}

export const api = {
  get: <T>(path: string, query?: Record<string, QueryValue>, options: RequestOptions = {}) =>
    request<T>("GET", path, { ...options, query }),
  post: <T>(path: string, body?: unknown, options: RequestOptions = {}) =>
    request<T>("POST", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options: RequestOptions = {}) =>
    request<T>("PATCH", path, { ...options, body }),
  page: <T>(path: string, query?: Record<string, QueryValue>, options: RequestOptions = {}) =>
    request<Page<T>>("GET", path, { ...options, query }),
};

/**
 * Walk a paginated collection, one page at a time. `next`/`previous` are
 * absolute URLs on the API host, so following them is explicit and bounded by
 * `maxPages` (default 20) to avoid an accidental unbounded crawl.
 */
export async function* iteratePages<T>(
  path: string,
  options: RequestOptions = {},
  maxPages = 20,
): AsyncGenerator<Page<T>, void, void> {
  let target: string | null = path;
  let firstRequest = true;
  let seen = 0;
  while (target !== null && seen < maxPages) {
    const page: Page<T> = await request<Page<T>>(
      "GET",
      target,
      firstRequest ? options : { signal: options.signal, onRequestId: options.onRequestId },
    );
    yield page;
    seen += 1;
    target = page.next;
    firstRequest = false;
  }
}

/** Collect every row across a paginated collection (bounded by `maxPages`). */
export async function collectPages<T>(
  path: string,
  options: RequestOptions = {},
  maxPages = 20,
): Promise<T[]> {
  const rows: T[] = [];
  for await (const page of iteratePages<T>(path, options, maxPages)) {
    rows.push(...page.results);
  }
  return rows;
}
