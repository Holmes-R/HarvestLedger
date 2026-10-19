import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import {
  API_BASE,
  ApiError,
  CLIENT_ERROR_CODES,
  api,
  assertWritablePayload,
  collectPages,
  generateRequestId,
  isAbortError,
  iteratePages,
  request,
  toApiError,
} from "./client";
import { createAdvance, createDeliveryCorrection, finalisePayout, getDelivery, listDeliveries } from "./endpoints";
import type { Delivery } from "./types";

type FetchImpl = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function stubFetch(impl: FetchImpl): Mock<FetchImpl> {
  const mock = vi.fn<FetchImpl>(impl);
  vi.stubGlobal("fetch", mock);
  return mock;
}

function jsonResponse(
  body: unknown,
  init: { status?: number; statusText?: string; requestId?: string } = {},
): Response {
  const headers = new Headers();
  if (init.requestId) headers.set("X-Request-ID", init.requestId);
  const status = init.status ?? 200;
  return {
    ok: status < 400,
    status,
    statusText: init.statusText ?? "",
    headers,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  } as unknown as Response;
}

function rawResponse(
  text: string,
  init: { status?: number; statusText?: string } = {},
): Response {
  const status = init.status ?? 200;
  return {
    ok: status < 400,
    status,
    statusText: init.statusText ?? "",
    headers: new Headers(),
    text: async () => text,
  } as unknown as Response;
}

function callUrl(mock: Mock<FetchImpl>, index = 0): string {
  return String(mock.mock.calls[index][0]);
}

function callHeaders(mock: Mock<FetchImpl>, index = 0): Record<string, string> {
  return (mock.mock.calls[index][1]?.headers ?? {}) as Record<string, string>;
}

async function catchApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (cause) {
    if (cause instanceof ApiError) return cause;
    throw cause;
  }
  throw new Error("Expected the request to reject.");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request basics", () => {
  it("parses JSON and keeps decimals as strings", async () => {
    const mock = stubFetch(async () =>
      jsonResponse({ amount: "245.00", net_kg: "99.87500", price: "24.50" }),
    );

    const data = await request<{ amount: string; net_kg: string }>("GET", "/deliveries/1/");

    expect(data.amount).toBe("245.00");
    expect(typeof data.amount).toBe("string");
    expect(data.net_kg).toBe("99.87500");
    expect(mock).toHaveBeenCalledTimes(1);
    expect(callUrl(mock)).toBe(`${API_BASE}/deliveries/1/`);
  });

  it("sends a well-formed X-Request-ID and prefers the server's id", async () => {
    const mock = stubFetch(async () => jsonResponse({ ok: true }, { requestId: "server12345678" }));
    const seen: string[] = [];

    await request("GET", "/health/", { onRequestId: (id) => seen.push(id) });

    expect(callHeaders(mock)["X-Request-ID"]).toMatch(/^[A-Za-z0-9._:-]{8,128}$/);
    expect(seen).toEqual(["server12345678"]);
  });

  it("builds query params and drops empty/undefined/null values", async () => {
    const mock = stubFetch(async () =>
      jsonResponse({ count: 0, next: null, previous: null, results: [] }),
    );

    await listDeliveries({ page: 2, farmer: undefined, kind: "", payout: 5 });

    const url = callUrl(mock);
    expect(url).toContain("page=2");
    expect(url).toContain("payout=5");
    expect(url).not.toContain("farmer=");
    expect(url).not.toContain("kind=");
  });

  it("returns undefined for an empty (non-JSON) success body", async () => {
    stubFetch(async () => rawResponse("", { status: 204, statusText: "No Content" }));

    const result = await finalisePayout(9);

    expect(result).toBeUndefined();
  });

  it("refuses an absolute URL outside the configured API base", async () => {
    const mock = stubFetch(async () => jsonResponse({}));

    const error = await catchApiError(request("GET", "https://evil.example.com/api/v1/farmers/"));

    expect(error.code).toBe(CLIENT_ERROR_CODES.invalidUrl);
    expect(mock).not.toHaveBeenCalled();
  });
});

describe("structured errors", () => {
  it("parses the envelope, field details and preserves the request id", async () => {
    stubFetch(async () =>
      jsonResponse(
        {
          error: {
            code: "original_not_settled",
            message: "The original delivery is not in a settled payout.",
            details: { kind: [{ code: "invalid", message: "bad kind" }] },
            request_id: "bodyrequest1",
          },
        },
        { status: 409, requestId: "headerrequest1" },
      ),
    );

    const error = await catchApiError(
      createAdvance({ farmer: 1, amount: "500.00", given_on: "2026-05-01" }),
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.code).toBe("original_not_settled");
    expect(error.requestId).toBe("bodyrequest1");
    expect(error.isWrite).toBe(true);
    expect(error.outcome).toBe("rejected");
    expect(error.outcomeUnknown).toBe(false);
    expect(error.reconciliation.safeToRetry).toBe(true);
    expect(error.fieldMessages()).toEqual(["kind: bad kind"]);
  });

  it("treats a 5xx write as an unknown outcome and never retries", async () => {
    const mock = stubFetch(async () =>
      jsonResponse(
        { error: { code: "internal_error", message: "boom", details: {}, request_id: "" } },
        { status: 500 },
      ),
    );

    const error = await catchApiError(
      createAdvance({ farmer: 1, amount: "500.00", given_on: "2026-05-01" }),
    );

    expect(mock).toHaveBeenCalledTimes(1);
    expect(error.outcome).toBe("unknown");
    expect(error.outcomeUnknown).toBe(true);
    expect(error.reconciliation.safeToRetry).toBe(false);
    expect(error.reconciliation.guidance).toMatch(/may or may not/);
  });

  it("treats a network failure as an unknown write, without retrying", async () => {
    const mock = stubFetch(async () => {
      throw new TypeError("Failed to fetch");
    });

    const error = await catchApiError(
      createAdvance({ farmer: 1, amount: "500.00", given_on: "2026-05-01" }),
    );

    expect(mock).toHaveBeenCalledTimes(1);
    expect(error.isNetworkError).toBe(true);
    expect(error.status).toBe(0);
    expect(error.outcome).toBe("unknown");
    expect(error.reconciliation.safeToRetry).toBe(false);
    expect(error.requestId).toMatch(/^[A-Za-z0-9._:-]{8,128}$/);
  });

  it("falls back safely when an error body is not JSON", async () => {
    stubFetch(async () => rawResponse("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" }));

    const error = await catchApiError(request("POST", "/deliveries/", { body: { farmer: 1 } }));

    expect(error.status).toBe(502);
    expect(error.code).toBe(CLIENT_ERROR_CODES.error);
    expect(error.message).toBe("Bad Gateway");
    expect(error.outcome).toBe("unknown");
    expect(error.requestId).toMatch(/^[A-Za-z0-9._:-]{8,128}$/);
  });
});

describe("cancellation", () => {
  it("raises request_aborted when the caller cancels in flight", async () => {
    stubFetch(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );

    const controller = new AbortController();
    const pending = getDelivery(1, { signal: controller.signal });
    controller.abort();

    const error = await catchApiError(pending);
    expect(error.isAborted).toBe(true);
    expect(error.code).toBe(CLIENT_ERROR_CODES.requestAborted);
    expect(error.outcome).toBe("unknown");
    expect(isAbortError(error)).toBe(true);
  });
});

describe("protected write payloads", () => {
  it("refuses a payload carrying a server-computed field, without calling the API", async () => {
    const mock = stubFetch(async () => jsonResponse({}));

    const error = await catchApiError(
      request("POST", "/deliveries/", { body: { farmer: 1, amount: "10.00" } }),
    );

    expect(error.code).toBe(CLIENT_ERROR_CODES.protectedPayload);
    expect(mock).not.toHaveBeenCalled();
  });

  it("accepts legal input fields only", () => {
    expect(() =>
      assertWritablePayload({ farmer: 1, crop_grade: 2, gross_weight_kg: "10.000" }),
    ).not.toThrow();
    expect(() => assertWritablePayload({ net_kg: "9.00000" })).toThrow(ApiError);
    // `amount` is the advance principal on /advances/, but computed elsewhere.
    expect(() => assertWritablePayload({ farmer: 1, amount: "500.00" }, "/advances/")).not.toThrow();
    expect(() => assertWritablePayload({ farmer: 1, amount: "10.00" }, "/deliveries/")).toThrow(ApiError);
  });
});

describe("pagination", () => {
  it("follows absolute next URLs and collects every row", async () => {
    const pages = [
      { count: 3, next: `${API_BASE}/deliveries/?page=2`, previous: null, results: [{ id: 1 }, { id: 2 }] },
      { count: 3, next: null, previous: `${API_BASE}/deliveries/`, results: [{ id: 3 }] },
    ];
    let call = 0;
    const mock = stubFetch(async () => jsonResponse(pages[call++]));

    const rows = await collectPages<{ id: number }>("/deliveries/");

    expect(rows.map((row) => row.id)).toEqual([1, 2, 3]);
    expect(mock).toHaveBeenCalledTimes(2);
    expect(callUrl(mock, 1)).toBe(`${API_BASE}/deliveries/?page=2`);
  });

  it("stops at maxPages to bound a runaway crawl", async () => {
    const mock = stubFetch(async () =>
      jsonResponse({ count: 999, next: `${API_BASE}/deliveries/?page=2`, previous: null, results: [] }),
    );

    let pages = 0;
    for await (const page of iteratePages("/deliveries/", {}, 2)) {
      pages += 1;
      expect(page.results).toEqual([]);
    }

    expect(pages).toBe(2);
    expect(mock).toHaveBeenCalledTimes(2);
  });

  it("types a single page explicitly", async () => {
    stubFetch(async () =>
      jsonResponse({ count: 1, next: null, previous: null, results: [{ id: 4 }] }),
    );

    const page = await api.page<Delivery>("/deliveries/");

    expect(page.count).toBe(1);
    expect(page.results[0].id).toBe(4);
    expect(page.next).toBeNull();
  });
});

describe("helpers", () => {
  it("generates well-formed, distinct request ids", () => {
    const first = generateRequestId();
    const second = generateRequestId();
    expect(first).toMatch(/^[A-Za-z0-9._:-]{8,128}$/);
    expect(first).not.toBe(second);
  });

  it("normalises unknown throws into an ApiError", () => {
    const error = toApiError(new Error("kaboom"));
    expect(error.code).toBe(CLIENT_ERROR_CODES.error);
    expect(error.status).toBe(0);
    expect(error.isWrite).toBe(false);
    expect(isAbortError(new Error("nope"))).toBe(false);
  });

  it("serialises dates on write bodies", async () => {
    const mock = stubFetch(async () => jsonResponse({ id: 1 }));
    await createDeliveryCorrection(3, { kind: "CREDIT_NOTE", magnitude: "245.00", reason: "short" });
    expect(callUrl(mock)).toBe(`${API_BASE}/deliveries/3/corrections/`);
    expect(mock.mock.calls[0][1]?.body).toBe(
      JSON.stringify({ kind: "CREDIT_NOTE", magnitude: "245.00", reason: "short" }),
    );
  });
});
