import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import { API_BASE } from "./client";
import {
  createAdvance,
  createDelivery,
  editDelivery,
  finalisePayout,
  generatePayout,
  markPayoutPaid,
  previewDelivery,
} from "./endpoints";

type FetchImpl = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function stubFetch(impl: FetchImpl): Mock<FetchImpl> {
  const mock = vi.fn<FetchImpl>(impl);
  vi.stubGlobal("fetch", mock);
  return mock;
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: new Headers(),
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function call(mock: Mock<FetchImpl>, index = 0) {
  const [input, init] = mock.mock.calls[index];
  return {
    url: String(input),
    method: init?.method,
    headers: (init?.headers ?? {}) as Record<string, string>,
    body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("write serialization", () => {
  it("posts a delivery with the input fields only", async () => {
    const mock = stubFetch(async () => jsonResponse({ id: 1 }));

    await createDelivery({
      farmer: 1,
      crop_grade: 2,
      delivered_on: "2026-05-01",
      gross_weight_kg: "100.125",
      moisture_percent: "16.00",
    });

    const sent = call(mock);
    expect(sent.url).toBe(`${API_BASE}/deliveries/`);
    expect(sent.method).toBe("POST");
    expect(sent.headers["Content-Type"]).toBe("application/json");
    expect(sent.body).toEqual({
      farmer: 1,
      crop_grade: 2,
      delivered_on: "2026-05-01",
      gross_weight_kg: "100.125",
      moisture_percent: "16.00",
    });
    expect(typeof sent.body.gross_weight_kg).toBe("string");
  });

  it("reduces an ISO instant to the IST calendar date", async () => {
    const mock = stubFetch(async () => jsonResponse({ id: 1 }));

    await createDelivery({
      farmer: 1,
      crop_grade: 2,
      delivered_on: "2026-05-01T06:00:00Z",
      gross_weight_kg: "10.000",
      moisture_percent: "14.00",
    });

    expect(call(mock).body.delivered_on).toBe("2026-05-01");
  });

  it("only serializes delivered_on on an edit when present", async () => {
    const mock = stubFetch(async () => jsonResponse({ id: 1 }));

    await editDelivery(7, { gross_weight_kg: "20.000" });
    await editDelivery(7, { delivered_on: "2026-05-01T06:00:00Z" });

    expect(call(mock, 0).body).toEqual({ gross_weight_kg: "20.000" });
    expect(call(mock, 1).body).toEqual({ delivered_on: "2026-05-01" });
  });

  it("previews a delivery against the preview route", async () => {
    const mock = stubFetch(async () => jsonResponse({ amount: "2450.00" }));

    await previewDelivery({
      farmer: 1,
      crop_grade: 2,
      delivered_on: "2026-05-01",
      gross_weight_kg: "100.000",
      moisture_percent: "14.00",
    });

    expect(call(mock).url).toBe(`${API_BASE}/deliveries/preview/`);
    expect(call(mock).method).toBe("POST");
  });

  it("posts an advance with a date-only given_on", async () => {
    const mock = stubFetch(async () => jsonResponse({ id: 1 }));

    await createAdvance({ farmer: 1, amount: "500.00", given_on: "2026-05-01T20:00:00Z" });

    // 20:00 UTC is already the next day in IST.
    expect(call(mock).body).toEqual({ farmer: 1, amount: "500.00", given_on: "2026-05-02" });
  });

  it("serializes the payout week_start", async () => {
    const mock = stubFetch(async () => jsonResponse({ payout: null, reason: "NO_ELIGIBLE_DELIVERIES" }));

    await generatePayout({ farmer: 1, week_start: "2026-04-29" });

    expect(call(mock).url).toBe(`${API_BASE}/payouts/generate/`);
    expect(call(mock).body).toEqual({ farmer: 1, week_start: "2026-04-29" });
  });

  it("sends body-less state transitions as POSTs with no content type", async () => {
    const mock = stubFetch(async () => jsonResponse({ id: 1 }));

    await finalisePayout(4);
    await markPayoutPaid(4);

    expect(call(mock, 0).url).toBe(`${API_BASE}/payouts/4/finalise/`);
    expect(call(mock, 0).method).toBe("POST");
    expect(call(mock, 0).body).toBeUndefined();
    expect(call(mock, 0).headers["Content-Type"]).toBeUndefined();
    expect(call(mock, 1).url).toBe(`${API_BASE}/payouts/4/mark-paid/`);
  });
});
