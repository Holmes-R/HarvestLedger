// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({
  getDelivery: vi.fn(),
  getPayout: vi.fn(),
  createDeliveryCorrection: vi.fn(),
}));
vi.mock("../api/lookups", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/lookups")>();
  return {
    ...actual,
    loadFarmerMap: vi.fn(),
    loadGradeMap: vi.fn(),
  };
});

import { getDelivery, getPayout, createDeliveryCorrection } from "../api/endpoints";
import { loadFarmerMap, loadGradeMap } from "../api/lookups";
import type {
  Correction,
  CropGrade,
  Delivery,
  Farmer,
  Payout,
} from "../api/types";
import { DeliveryDetail } from "./DeliveryDetail";

const getDeliveryMock = vi.mocked(getDelivery);
const getPayoutMock = vi.mocked(getPayout);
const createCorrectionMock = vi.mocked(createDeliveryCorrection);
const loadFarmerMapMock = vi.mocked(loadFarmerMap);
const loadGradeMapMock = vi.mocked(loadGradeMap);

const farmer: Farmer = {
  id: 1,
  name: "Ravi Kumar",
  phone: "9876543210",
  village: "Kolar",
  bank_reference: "",
  outstanding_advance: "321.00",
  created_at: "2026-05-01T10:00:00+05:30",
};

const grade: CropGrade = {
  id: 10,
  crop: 2,
  crop_name: "Paddy",
  code: "A",
  created_at: "2026-05-01T10:00:00+05:30",
};

const delivery: Delivery = {
  id: 31,
  farmer: 1,
  kind: "PROCUREMENT",
  crop_grade: 10,
  delivered_on: "2026-10-13",
  accounting_date: "2026-10-13",
  gross_weight_kg: "120.500",
  moisture_percent: "12.00",
  threshold_used: "14.00",
  deduction_percent: "0.00",
  deduction_kg: "0.00000",
  net_kg: "120.50000",
  applied_price: "25.25",
  price_list_entry: 5,
  amount: "3042.63",
  calculation_version: 1,
  original_delivery: null,
  correction_magnitude: null,
  reason: "",
  payout: 7,
  recorded_at: "2026-10-13T10:00:00+05:30",
};

const payout: Payout = {
  id: 7,
  farmer: 1,
  farmer_name: "Ravi Kumar",
  week_start: "2026-10-12",
  week_end: "2026-10-18",
  status: "DRAFT",
  gross_amount: "3042.63",
  advance_deduction: "0.00",
  net_amount: "3042.63",
  deliveries: [delivery],
  created_at: "2026-10-18T10:00:00+05:30",
  finalised_at: null,
  paid_at: null,
};

const correction: Correction = {
  id: 88,
  farmer: 1,
  kind: "CREDIT_NOTE",
  original_delivery: 31,
  correction_magnitude: "50.00",
  reason: "quality allowance",
  accounting_date: "2026-10-20",
  amount: "50.00",
  payout: null,
  recorded_at: "2026-10-20T10:00:00+05:30",
};

beforeEach(() => {
  window.location.hash = "#/deliveries/31";
  getDeliveryMock.mockReset();
  getPayoutMock.mockReset();
  createCorrectionMock.mockReset();
  loadFarmerMapMock.mockReset();
  loadGradeMapMock.mockReset();
  getDeliveryMock.mockResolvedValue(delivery);
  getPayoutMock.mockResolvedValue(payout);
  loadFarmerMapMock.mockResolvedValue(new Map([[farmer.id, farmer]]));
  loadGradeMapMock.mockResolvedValue(new Map([[grade.id, grade]]));
});

afterEach(cleanup);

describe("DeliveryDetail corrections", () => {
  it("does not offer a correction while the original payout is a Draft", async () => {
    render(<DeliveryDetail deliveryId={31} onBack={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Delivery #31" })).toBeTruthy();
    expect(await screen.findByText(/still a Draft/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add correction" })).toBeNull();
  });

  it("keeps editing and corrections unavailable when settlement cannot be confirmed", async () => {
    getPayoutMock.mockRejectedValue(new Error("network down"));
    render(<DeliveryDetail deliveryId={31} onBack={vi.fn()} />);

    const edit = await screen.findByRole(
      "button",
      { name: "Settlement unavailable" },
      { timeout: 5000 },
    );
    expect((edit as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText(/Settlement status could not be confirmed/),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add correction" })).toBeNull();
  });

  it("records a linked note for a Finalised original and shows the new link", async () => {
    const user = userEvent.setup();
    getPayoutMock.mockResolvedValue({
      ...payout,
      status: "FINALISED",
      finalised_at: "2026-10-19T10:00:00+05:30",
    });
    createCorrectionMock.mockResolvedValue(correction);
    render(<DeliveryDetail deliveryId={31} onBack={vi.fn()} />);

    const add = await screen.findByRole(
      "button",
      { name: "Add correction" },
      { timeout: 5000 },
    );
    await user.click(add);

    expect(
      await screen.findByRole("heading", { name: "Correct delivery #31" }),
    ).toBeTruthy();
    expect(screen.getAllByText("Ravi Kumar").length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText("Magnitude (INR)"), "50.00");
    await user.type(screen.getByLabelText("Reason"), "quality allowance");
    await user.click(screen.getByRole("button", { name: "Record note" }));

    expect(
      await screen.findByText(/Correction note #88 recorded for delivery #31/),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Open note #88" }),
    ).toBeTruthy();
    expect(createCorrectionMock).toHaveBeenCalledWith(31, {
      kind: "CREDIT_NOTE",
      magnitude: "50.00",
      reason: "quality allowance",
    });
    // The original read is refreshed; the frozen delivery is never patched.
    expect(getDeliveryMock).toHaveBeenCalledTimes(2);
  });
});
