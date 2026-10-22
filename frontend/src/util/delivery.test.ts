import { describe, expect, it } from "vitest";

import type { Delivery, DeliveryPreview } from "../api/types";
import {
  comparePreviewToStored,
  correctionEligibility,
  deliveryLockReason,
  gradeBelongsToCrop,
  moneyDelta,
  validateDeliveryInputs,
  type DeliveryInput,
} from "./delivery";

const validInput: DeliveryInput = {
  farmerId: "1",
  cropId: "2",
  gradeId: "10",
  deliveredOn: "2026-05-01",
  gross: "100.125",
  moisture: "16.00",
};

const preview: DeliveryPreview = {
  farmer_id: 1,
  crop_grade: 10,
  delivered_on: "2026-05-01",
  accounting_date: "2026-05-04",
  business_date: "2026-05-01",
  gross_weight_kg: "100.125",
  moisture_percent: "16.00",
  threshold_used: "14.00",
  applied_price: "24.50",
  price_list_entry: 5,
  deduction_percent: "2.00",
  deduction_kg: "2.00500",
  net_kg: "98.12000",
  amount: "2403.94",
};

const stored: Delivery = {
  id: 7,
  farmer: 1,
  kind: "PROCUREMENT",
  crop_grade: 10,
  delivered_on: "2026-05-01",
  accounting_date: "2026-05-04",
  gross_weight_kg: "100.125",
  moisture_percent: "16.00",
  threshold_used: "14.00",
  deduction_percent: "2.00",
  deduction_kg: "2.00500",
  net_kg: "98.12000",
  applied_price: "25.00",
  price_list_entry: 6,
  amount: "2453.00",
  calculation_version: 1,
  original_delivery: null,
  correction_magnitude: null,
  reason: "",
  payout: null,
  recorded_at: "2026-05-01T14:30:00+05:30",
};

describe("validateDeliveryInputs", () => {
  it("accepts a complete, well-formed input", () => {
    expect(validateDeliveryInputs(validInput)).toEqual({
      farmer: null,
      crop: null,
      grade: null,
      date: null,
      gross: null,
      moisture: null,
      valid: true,
    });
  });

  it("requires every input", () => {
    const result = validateDeliveryInputs({
      farmerId: "",
      cropId: "",
      gradeId: "",
      deliveredOn: "",
      gross: "",
      moisture: "",
    });
    expect(result.valid).toBe(false);
    expect(result.farmer).toBe("Select a farmer.");
    expect(result.crop).toBe("Select a crop.");
    expect(result.grade).toBe("Select a grade.");
    expect(result.date).toBe("Select a delivery date.");
    expect(result.gross).toBe("Required.");
    expect(result.moisture).toBe("Required.");
  });

  it("rejects too many decimal places and non-positive weights", () => {
    const result = validateDeliveryInputs({
      ...validInput,
      gross: "100.1234",
      moisture: "0",
    });
    expect(result.valid).toBe(false);
    expect(result.gross).toMatch(/3 decimal places/);
    expect(result.moisture).toMatch(/greater than zero/);
  });

  it("rejects an impossible delivery date", () => {
    const result = validateDeliveryInputs({
      ...validInput,
      deliveredOn: "2026-02-30",
    });
    expect(result.valid).toBe(false);
    expect(result.date).toBe("Enter a valid date (YYYY-MM-DD).");
  });
});

describe("gradeBelongsToCrop", () => {
  it("matches by crop id", () => {
    expect(gradeBelongsToCrop({ crop: 2 }, "2")).toBe(true);
    expect(gradeBelongsToCrop({ crop: 2 }, "3")).toBe(false);
    expect(gradeBelongsToCrop(undefined, "2")).toBe(false);
    expect(gradeBelongsToCrop({ crop: 2 }, "")).toBe(false);
  });
});

describe("comparePreviewToStored", () => {
  it("reports a price change and its money delta", () => {
    const comparison = comparePreviewToStored(preview, stored);
    expect(comparison.changed).toBe(true);
    const price = comparison.fields.find((field) => field.key === "applied_price");
    expect(price).toMatchObject({
      preview: "24.50",
      stored: "25.00",
      changed: true,
    });
    const entry = comparison.fields.find((field) => field.key === "price_list_entry");
    expect(entry).toMatchObject({ preview: "#5", stored: "#6", changed: true });
    expect(comparison.amountDelta).toBe("+₹49.06");
  });

  it("reports no change when the stored breakdown matches", () => {
    const unchanged: Delivery = {
      ...stored,
      applied_price: preview.applied_price,
      price_list_entry: preview.price_list_entry,
      amount: preview.amount,
    };
    const comparison = comparePreviewToStored(preview, unchanged);
    expect(comparison.changed).toBe(false);
    expect(comparison.fields.every((field) => !field.changed)).toBe(true);
    expect(comparison.amountDelta).toBe("₹0.00");
  });
});

describe("moneyDelta", () => {
  it("works in minor units without floats", () => {
    expect(moneyDelta("2403.94", "2453.00")).toBe("+₹49.06");
    expect(moneyDelta("2453.00", "2403.94")).toBe("-₹49.06");
    expect(moneyDelta("0.10", "0.30")).toBe("+₹0.20");
    expect(moneyDelta("123456.78", "123456.78")).toBe("₹0.00");
  });

  it("returns null for unparseable or missing values", () => {
    expect(moneyDelta("abc", "1.00")).toBeNull();
    expect(moneyDelta("1.234", "1.00")).toBeNull();
    expect(moneyDelta(null, "1.00")).toBeNull();
  });
});

describe("deliveryLockReason", () => {
  const procurement = { kind: "PROCUREMENT" as const, payout: 4 };

  it("allows a procurement delivery without a settled payout", () => {
    expect(deliveryLockReason({ kind: "PROCUREMENT", payout: null })).toBeNull();
    expect(deliveryLockReason(procurement, "DRAFT")).toBeNull();
  });

  it("locks a delivery in a finalised or paid payout", () => {
    expect(deliveryLockReason(procurement, "FINALISED")).toMatch(
      /finalised payout/,
    );
    expect(deliveryLockReason(procurement, "PAID")).toMatch(/paid payout/);
  });

  it("always locks correction notes", () => {
    expect(
      deliveryLockReason({ kind: "CREDIT_NOTE", payout: null }, "DRAFT"),
    ).toMatch(/immutable/);
  });
});

describe("correctionEligibility", () => {
  const procurement = { kind: "PROCUREMENT" as const, payout: 4 };

  it("offers corrections only for a Finalised or Paid original payout", () => {
    expect(correctionEligibility(procurement, "FINALISED")).toEqual({
      available: true,
      checking: false,
      reason: null,
    });
    expect(correctionEligibility(procurement, "PAID").available).toBe(true);
  });

  it("does not offer corrections for a Draft or unassigned original", () => {
    expect(correctionEligibility(procurement, "DRAFT")).toMatchObject({
      available: false,
      checking: false,
    });
    expect(
      correctionEligibility({ kind: "PROCUREMENT", payout: null }),
    ).toMatchObject({ available: false, checking: false });
  });

  it("does not offer corrections against another correction note", () => {
    expect(
      correctionEligibility({ kind: "DEBIT_NOTE", payout: 4 }, "PAID"),
    ).toMatchObject({ available: false, checking: false });
  });

  it("reports that settlement is still being checked", () => {
    expect(correctionEligibility(procurement)).toEqual({
      available: false,
      checking: true,
      reason: null,
    });
  });
});
