// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({ previewDelivery: vi.fn() }));

import { ApiError } from "../api/client";
import { previewDelivery } from "../api/endpoints";
import type { DeliveryPreview, DeliveryWrite } from "../api/types";
import { useDeliveryPreview } from "./useDeliveryPreview";

const previewDeliveryMock = vi.mocked(previewDelivery);

const bodyA: DeliveryWrite = {
  farmer: 1,
  crop_grade: 10,
  delivered_on: "2026-05-01",
  gross_weight_kg: "100.125",
  moisture_percent: "16.00",
};

const bodyB: DeliveryWrite = { ...bodyA, moisture_percent: "15.50" };

function preview(amount: string, price: string): DeliveryPreview {
  return {
    farmer_id: 1,
    crop_grade: 10,
    delivered_on: "2026-05-01",
    accounting_date: "2026-05-04",
    business_date: "2026-05-01",
    gross_weight_kg: "100.125",
    moisture_percent: "16.00",
    threshold_used: "14.00",
    applied_price: price,
    price_list_entry: 5,
    deduction_percent: "2.00",
    deduction_kg: "2.00500",
    net_kg: "98.12000",
    amount,
  };
}

const previewA = preview("2403.94", "24.50");
const previewB = preview("2453.00", "25.00");

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.useFakeTimers();
  previewDeliveryMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useDeliveryPreview", () => {
  it("does nothing while the body is null", () => {
    const { result } = renderHook(() => useDeliveryPreview(null));
    expect(result.current).toEqual({
      preview: undefined,
      error: undefined,
      loading: false,
    });
    expect(previewDeliveryMock).not.toHaveBeenCalled();
  });

  it("debounces rapid input changes, requesting only the latest body", async () => {
    const pending = deferred<DeliveryPreview>();
    previewDeliveryMock.mockReturnValue(pending.promise);

    const { result, rerender } = renderHook(
      ({ body }: { body: DeliveryWrite | null }) =>
        useDeliveryPreview(body, { delay: 300 }),
      { initialProps: { body: bodyA } },
    );

    expect(result.current.loading).toBe(true);
    expect(previewDeliveryMock).not.toHaveBeenCalled();

    rerender({ body: bodyB });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(previewDeliveryMock).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(previewDeliveryMock).toHaveBeenCalledTimes(1);
    expect(previewDeliveryMock).toHaveBeenCalledWith(
      bodyB,
      expect.objectContaining({ signal: expect.anything() }),
    );

    await act(async () => {
      pending.resolve(previewB);
      await pending.promise;
    });
    expect(result.current.preview).toEqual(previewB);
    expect(result.current.loading).toBe(false);
  });

  it("ignores a slow older response after the inputs change", async () => {
    const first = deferred<DeliveryPreview>();
    const second = deferred<DeliveryPreview>();
    previewDeliveryMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { result, rerender } = renderHook(
      ({ body }: { body: DeliveryWrite | null }) =>
        useDeliveryPreview(body, { delay: 0 }),
      { initialProps: { body: bodyA } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(previewDeliveryMock).toHaveBeenCalledTimes(1);

    rerender({ body: bodyB });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(previewDeliveryMock).toHaveBeenCalledTimes(2);
    const firstSignal = previewDeliveryMock.mock.calls[0][1]?.signal;
    expect(firstSignal?.aborted).toBe(true);

    await act(async () => {
      second.resolve(previewB);
      await second.promise;
    });
    expect(result.current.preview?.amount).toBe("2453.00");

    await act(async () => {
      first.resolve(previewA);
      await first.promise;
    });
    expect(result.current.preview?.amount).toBe("2453.00");
  });

  it("invalidates the current preview immediately when an input changes", async () => {
    const first = deferred<DeliveryPreview>();
    const second = deferred<DeliveryPreview>();
    previewDeliveryMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { result, rerender } = renderHook(
      ({ body }: { body: DeliveryWrite | null }) =>
        useDeliveryPreview(body, { delay: 0 }),
      { initialProps: { body: bodyA } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      first.resolve(previewA);
      await first.promise;
    });
    expect(result.current.preview).toEqual(previewA);

    rerender({ body: bodyB });
    expect(result.current.preview).toBeUndefined();
    expect(result.current.loading).toBe(true);
  });

  it("surfaces an inline preview error and stops loading", async () => {
    const error = new ApiError({
      status: 422,
      code: "price_not_found",
      message: "No effective price for this grade on that date.",
    });
    previewDeliveryMock.mockRejectedValue(error);

    const { result } = renderHook(() =>
      useDeliveryPreview(bodyA, { delay: 0 }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect(result.current.error?.code).toBe("price_not_found");
    expect(result.current.preview).toBeUndefined();
    expect(result.current.loading).toBe(false);
    expect(previewDeliveryMock).toHaveBeenCalledTimes(1);
  });
});
