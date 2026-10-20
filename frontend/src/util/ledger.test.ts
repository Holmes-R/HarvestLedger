import { describe, expect, it } from "vitest";

import type {
  LedgerDelivery,
  LedgerEvent,
  LedgerPayout,
  LedgerSummary,
} from "../api/types";
import {
  earningsIdentityText,
  isLedgerFiltered,
  ledgerAmountMeaning,
  ledgerBackTarget,
  ledgerContextLink,
  ledgerContextSuffix,
  ledgerDeliveryPayoutLabel,
  ledgerEmptyMessage,
  ledgerEventTitle,
  ledgerEventTone,
  ledgerPayoutStateNote,
  payoutArithmeticWarnings,
} from "./ledger";

const procurement: LedgerDelivery = {
  id: 31,
  kind: "PROCUREMENT",
  crop_grade: 10,
  delivered_on: "2026-10-13",
  accounting_date: "2026-10-13",
  gross_weight_kg: "120.500",
  moisture_percent: "12.00",
  net_kg: "118.09000",
  applied_price: "25.75",
  amount: "3040.82",
  payout: 7,
  original_delivery: null,
  correction_magnitude: null,
  reason: "",
  is_correction: false,
  is_assigned: true,
  signed_amount: "3040.82",
};

const credit: LedgerDelivery = {
  ...procurement,
  id: 32,
  kind: "CREDIT_NOTE",
  crop_grade: null,
  delivered_on: null,
  accounting_date: "2026-10-18",
  gross_weight_kg: null,
  moisture_percent: null,
  net_kg: null,
  applied_price: null,
  amount: "50.00",
  payout: null,
  original_delivery: 31,
  correction_magnitude: "50.00",
  reason: "quality allowance",
  is_correction: true,
  is_assigned: false,
  signed_amount: "50.00",
};

const debit: LedgerDelivery = {
  ...credit,
  id: 33,
  kind: "DEBIT_NOTE",
  amount: "-25.00",
  correction_magnitude: "25.00",
  signed_amount: "-25.00",
};

function payout(overrides: Partial<LedgerPayout> = {}): LedgerPayout {
  return {
    id: 7,
    week_start: "2026-10-12",
    week_end: "2026-10-18",
    status: "DRAFT",
    gross_amount: "3040.82",
    advance_deduction: "0.00",
    net_amount: "3040.82",
    finalised_at: null,
    paid_at: null,
    delivery_ids: [31],
    member_total: "3040.82",
    is_draft: true,
    is_settled: false,
    gross_matches_members: true,
    net_equals_gross_minus_deduction: true,
    ...overrides,
  };
}

function summary(overrides: Partial<LedgerSummary> = {}): LedgerSummary {
  return {
    farmer_id: 2,
    name: "Ravi Kumar",
    phone: "9876543210",
    outstanding_advance: "500.00",
    reconciliation: {
      farmer_id: 2,
      total_advances: "700.00",
      total_recovered: "200.00",
      expected_outstanding: "500.00",
      stored_outstanding: "500.00",
      difference: "0.00",
      is_reconciled: true,
    },
    total_advances: "700.00",
    settled_earnings: "2450.00",
    total_recovered: "200.00",
    draft_projection: "300.00",
    unassigned_earnings: "50.00",
    total_recorded_amount: "2800.00",
    earnings_identity_holds: true,
    is_reconciled: true,
    history_from: null,
    history_to: null,
    ...overrides,
  };
}

function event(overrides: Partial<LedgerEvent>): LedgerEvent {
  return {
    event_type: "DELIVERY",
    id: 31,
    date: "2026-10-13",
    amount: "3040.82",
    delivery: procurement,
    advance: null,
    payout: null,
    ...overrides,
  };
}

describe("ledger helpers", () => {
  it("tones payouts by status and corrections by sign kind", () => {
    expect(ledgerEventTone(event({}))).toBe("procurement");
    expect(
      ledgerEventTone(event({ event_type: "CORRECTION", delivery: credit })),
    ).toBe("credit");
    expect(
      ledgerEventTone(event({ event_type: "CORRECTION", delivery: debit })),
    ).toBe("debit");
    expect(ledgerEventTone(event({ event_type: "ADVANCE", delivery: null }))).toBe(
      "warn",
    );
    expect(
      ledgerEventTone(
        event({
          event_type: "PAYOUT",
          delivery: null,
          payout: payout({ status: "DRAFT" }),
        }),
      ),
    ).toBe("draft");
    expect(
      ledgerEventTone(
        event({
          event_type: "PAYOUT",
          delivery: null,
          payout: payout({ status: "PAID", is_draft: false, is_settled: true }),
        }),
      ),
    ).toBe("paid");
  });

  it("names each event kind and the meaning of its signed amount", () => {
    expect(ledgerEventTitle(event({}))).toBe("Delivery #31");
    expect(
      ledgerEventTitle(
        event({ event_type: "CORRECTION", id: 32, delivery: credit }),
      ),
    ).toBe("Credit note #32");
    expect(
      ledgerEventTitle(
        event({ event_type: "CORRECTION", id: 33, delivery: debit }),
      ),
    ).toBe("Debit note #33");
    expect(ledgerEventTitle(event({ event_type: "ADVANCE", delivery: null }))).toBe(
      "Advance #31",
    );
    expect(ledgerEventTitle(event({ event_type: "PAYOUT", delivery: null }))).toBe(
      "Payout #31",
    );

    expect(ledgerAmountMeaning(event({}))).toBe("Earning");
    expect(
      ledgerAmountMeaning(event({ event_type: "CORRECTION", delivery: credit })),
    ).toBe("Credit to farmer");
    expect(
      ledgerAmountMeaning(event({ event_type: "CORRECTION", delivery: debit })),
    ).toBe("Debit from farmer");
    expect(ledgerAmountMeaning(event({ event_type: "ADVANCE" }))).toBe(
      "Advance given",
    );
    expect(
      ledgerAmountMeaning(
        event({ event_type: "PAYOUT", payout: payout({ status: "DRAFT" }) }),
      ),
    ).toBe("Draft net (projection)");
    expect(
      ledgerAmountMeaning(
        event({
          event_type: "PAYOUT",
          payout: payout({ status: "FINALISED", is_draft: false }),
        }),
      ),
    ).toBe("Net payable");
  });

  it("labels draft recovery as a projection and settled recovery as once-only", () => {
    expect(ledgerPayoutStateNote(payout())).toContain("not yet applied");
    expect(
      ledgerPayoutStateNote(payout({ status: "FINALISED", is_draft: false })),
    ).toContain("once at finalisation");
    expect(
      ledgerPayoutStateNote(
        payout({ status: "PAID", is_draft: false, is_settled: true }),
      ),
    ).toContain("not again when paid");
  });

  it("flags payout arithmetic mismatches instead of silently trusting them", () => {
    expect(payoutArithmeticWarnings(payout())).toEqual([]);
    expect(
      payoutArithmeticWarnings(
        payout({ gross_matches_members: false, net_equals_gross_minus_deduction: false }),
      ),
    ).toHaveLength(2);
  });

  it("describes delivery assignment", () => {
    expect(ledgerDeliveryPayoutLabel(procurement)).toBe("In payout #7");
    expect(ledgerDeliveryPayoutLabel(credit)).toBe("Not in a payout yet");
  });

  it("explains empty history versus an empty filter window", () => {
    expect(ledgerEmptyMessage(false)).toContain("No ledger activity yet");
    expect(ledgerEmptyMessage(true)).toContain("match this date window");
    expect(isLedgerFiltered("", "", "")).toBe(false);
    expect(isLedgerFiltered("2026-10-01", "", "")).toBe(true);
    expect(isLedgerFiltered("", "", "PAYOUT")).toBe(true);
  });

  it("shows the earnings identity without adding payouts and their members twice", () => {
    const text = earningsIdentityText(summary());
    expect(text).toContain("Settled");
    expect(text).toContain("2,450.00");
    expect(text).toContain("Draft");
    expect(text).toContain("300.00");
    expect(text).toContain("Unassigned");
    expect(text).toContain("50.00");
    expect(text).toContain("2,800.00 recorded");
    expect(text).toContain(" = ");
  });

  it("builds links that carry the farmer back to this ledger", () => {
    expect(ledgerContextLink("deliveries", 12, "3")).toBe(
      "#/deliveries/12?from=ledger&farmer=3",
    );
    expect(ledgerContextLink("payouts", 8, 3)).toBe(
      "#/payouts/8?from=ledger&farmer=3",
    );

    const params = new URLSearchParams("from=ledger&farmer=3");
    expect(ledgerContextSuffix(params)).toBe("?from=ledger&farmer=3");
    expect(ledgerBackTarget(params)).toBe("#/ledger?from=ledger&farmer=3");

    const plain = new URLSearchParams("farmer=3");
    expect(ledgerContextSuffix(plain)).toBe("");
    expect(ledgerBackTarget(plain)).toBeNull();
  });
});
