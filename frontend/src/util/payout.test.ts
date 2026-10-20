import { describe, expect, it } from "vitest";

import type { Payout } from "../api/types";
import {
  classifyGeneration,
  finaliseConfirmation,
  generateEmptyMessage,
  isNonPositiveMoney,
  isPayoutStateConflict,
  isSupplementary,
  markPaidConfirmation,
  nonPositiveNote,
  payoutActions,
  sameWeekStatements,
} from "./payout";

function payout(overrides: Partial<Payout> = {}): Payout {
  return {
    id: 7,
    farmer: 2,
    farmer_name: "Ravi Kumar",
    week_start: "2026-10-12",
    week_end: "2026-10-18",
    status: "DRAFT",
    gross_amount: "1000.00",
    advance_deduction: "0.00",
    net_amount: "1000.00",
    deliveries: [],
    created_at: "2026-10-19T10:00:00+05:30",
    finalised_at: null,
    paid_at: null,
    ...overrides,
  };
}

describe("payout helpers", () => {
  it("recognises zero and negative money without parsing decimals", () => {
    for (const value of ["0", "0.00", "00.00", "-0.01", "-100.00"]) {
      expect(isNonPositiveMoney(value)).toBe(true);
    }
    for (const value of ["0.01", "100.00", null, undefined, ""]) {
      expect(isNonPositiveMoney(value)).toBe(false);
    }
  });

  it("allows Finalise only from Draft and Mark paid only from Finalised", () => {
    expect(payoutActions("DRAFT")).toEqual({
      canFinalise: true,
      canMarkPaid: false,
      readOnlyReason: null,
    });
    expect(payoutActions("FINALISED")).toEqual({
      canFinalise: false,
      canMarkPaid: true,
      readOnlyReason: null,
    });
    const paid = payoutActions("PAID");
    expect(paid.canFinalise).toBe(false);
    expect(paid.canMarkPaid).toBe(false);
    expect(paid.readOnlyReason).toMatch(/read-only/i);
  });

  it("finds earlier and later statements for the same farmer and week", () => {
    const current = payout({ id: 7 });
    const earlier = payout({ id: 4, status: "FINALISED" });
    const later = payout({ id: 9, status: "DRAFT" });
    const otherWeek = payout({ id: 6, week_start: "2026-10-05" });
    const otherFarmer = payout({ id: 8, farmer: 3 });

    expect(sameWeekStatements(current, [later, current, otherWeek, earlier, otherFarmer]))
      .toEqual([earlier, later]);
    expect(isSupplementary(current, [earlier, current])).toBe(true);
    expect(isSupplementary(earlier, [earlier, current])).toBe(false);
  });

  it("decodes the documented generation envelope", () => {
    const draft = payout({});
    expect(classifyGeneration({ payout: draft, reason: null })).toEqual({
      kind: "draft",
      payout: draft,
    });
    expect(
      classifyGeneration({ payout: null, reason: "NO_ELIGIBLE_DELIVERIES" }),
    ).toEqual({ kind: "empty", reason: "NO_ELIGIBLE_DELIVERIES" });
    expect(generateEmptyMessage("NO_ELIGIBLE_DELIVERIES")).toMatch(
      /nothing was generated and no balance changed/i,
    );
    expect(generateEmptyMessage("OTHER")).toMatch(/OTHER/);
  });

  it("shows the intended farmer, week and money in confirmations", () => {
    const draft = payout({});
    const finalise = finaliseConfirmation(draft);
    expect(finalise).toContain("Ravi Kumar");
    expect(finalise).toContain("2026-10-12 to 2026-10-18");
    expect(finalise).toContain("₹1,000.00");
    expect(finalise).toMatch(/cannot be undone/i);

    const paid = markPaidConfirmation(
      payout({ status: "FINALISED", advance_deduction: "300.00", net_amount: "700.00" }),
    );
    expect(paid).toContain("₹700.00");
    expect(paid).toMatch(/does not recover the advance again/i);
  });

  it("explains the non-positive policy for drafts and settled statements", () => {
    expect(
      nonPositiveNote(payout({ gross_amount: "0.00", net_amount: "0.00" })),
    ).toMatch(/payable as-is/i);
    expect(
      nonPositiveNote(
        payout({ status: "FINALISED", net_amount: "-50.00", gross_amount: "-50.00" }),
      ),
    ).toMatch(/pays it as-is/i);
    expect(nonPositiveNote(payout({ gross_amount: "10.00", net_amount: "10.00" })))
      .toBeNull();
  });

  it("detects only the documented 409 state conflict", () => {
    expect(isPayoutStateConflict({ status: 409, code: "payout_state_error" })).toBe(true);
    expect(isPayoutStateConflict({ status: 409, code: "conflict" })).toBe(false);
    expect(isPayoutStateConflict({ status: 400, code: "payout_state_error" })).toBe(false);
  });
});
