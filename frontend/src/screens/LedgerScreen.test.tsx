// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/lookups", () => ({
  loadFarmerMap: vi.fn(),
  loadGradeMap: vi.fn(),
}));
vi.mock("../api/endpoints", () => ({ getLedger: vi.fn() }));

import { ApiError } from "../api/client";
import { getLedger } from "../api/endpoints";
import { loadFarmerMap, loadGradeMap } from "../api/lookups";
import type {
  CropGrade,
  Farmer,
  LedgerDelivery,
  LedgerEvent,
  LedgerPage,
  LedgerPayout,
  LedgerSummary,
} from "../api/types";
import { LedgerScreen } from "./LedgerScreen";

const getLedgerMock = vi.mocked(getLedger);
const loadFarmerMapMock = vi.mocked(loadFarmerMap);
const loadGradeMapMock = vi.mocked(loadGradeMap);

const farmer: Farmer = {
  id: 2,
  name: "Ravi Kumar",
  phone: "9876543210",
  village: "Kolar",
  bank_reference: "SBIN0001234",
  outstanding_advance: "321.00",
  created_at: "2026-01-01T10:00:00+05:30",
};

const farmerMap = new Map<number, Farmer>([[farmer.id, farmer]]);
const gradeMap = new Map<number, CropGrade>();

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

const creditNote: LedgerDelivery = {
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

const debitNote: LedgerDelivery = {
  ...creditNote,
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

const draftPayout = payout();
const paidPayout = payout({
  id: 8,
  status: "PAID",
  advance_deduction: "200.00",
  net_amount: "2840.82",
  finalised_at: "2026-10-19T10:00:00+05:30",
  paid_at: "2026-10-20T10:00:00+05:30",
  is_draft: false,
  is_settled: true,
});

const deliveryEvent: LedgerEvent = {
  event_type: "DELIVERY",
  id: 31,
  date: "2026-10-13",
  amount: "3040.82",
  delivery: procurement,
  advance: null,
  payout: null,
};

const creditEvent: LedgerEvent = {
  event_type: "CORRECTION",
  id: 32,
  date: "2026-10-18",
  amount: "50.00",
  delivery: creditNote,
  advance: null,
  payout: null,
};

const debitEvent: LedgerEvent = {
  event_type: "CORRECTION",
  id: 33,
  date: "2026-10-18",
  amount: "-25.00",
  delivery: debitNote,
  advance: null,
  payout: null,
};

const advanceEvent: LedgerEvent = {
  event_type: "ADVANCE",
  id: 4,
  date: "2026-10-01",
  amount: "500.00",
  delivery: null,
  advance: {
    id: 4,
    amount: "500.00",
    given_on: "2026-10-01",
    created_at: "2026-10-01T09:00:00+05:30",
  },
  payout: null,
};

const draftPayoutEvent: LedgerEvent = {
  event_type: "PAYOUT",
  id: 7,
  date: "2026-10-12",
  amount: draftPayout.net_amount,
  delivery: null,
  advance: null,
  payout: draftPayout,
};

const paidPayoutEvent: LedgerEvent = {
  event_type: "PAYOUT",
  id: 8,
  date: "2026-10-12",
  amount: paidPayout.net_amount,
  delivery: null,
  advance: null,
  payout: paidPayout,
};

function summary(overrides: Partial<LedgerSummary> = {}): LedgerSummary {
  return {
    farmer_id: farmer.id,
    name: farmer.name,
    phone: farmer.phone,
    outstanding_advance: "321.00",
    reconciliation: {
      farmer_id: farmer.id,
      total_advances: "700.00",
      total_recovered: "200.00",
      expected_outstanding: "321.00",
      stored_outstanding: "321.00",
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

function page(
  results: LedgerEvent[],
  overrides: Partial<LedgerPage> = {},
): LedgerPage {
  return {
    count: results.length,
    next: null,
    previous: null,
    summary: summary(),
    results,
    ...overrides,
  };
}

function lastQuery(): Record<string, unknown> {
  const calls = getLedgerMock.mock.calls;
  return calls[calls.length - 1][1] as Record<string, unknown>;
}

function outstandingText(): string | null | undefined {
  return screen.getByText("Outstanding advance").nextElementSibling?.textContent;
}

beforeEach(() => {
  window.location.hash = "#/ledger";
  loadFarmerMapMock.mockReset();
  loadGradeMapMock.mockReset();
  getLedgerMock.mockReset();
  loadFarmerMapMock.mockResolvedValue(farmerMap);
  loadGradeMapMock.mockResolvedValue(gradeMap);
});

afterEach(cleanup);

describe("LedgerScreen", () => {
  it("shows farmer details and the authoritative account summary, not a page-derived balance", async () => {
    getLedgerMock.mockResolvedValue(
      page([deliveryEvent], { count: 25, next: "http://api/next" }),
    );
    render(<LedgerScreen initialFarmerId="2" />);

    expect(await screen.findByRole("heading", { name: "Ravi Kumar" })).toBeTruthy();
    expect(getLedgerMock).toHaveBeenCalledWith(
      2,
      expect.objectContaining({ page: 1, ordering: "-date" }),
      expect.anything(),
    );

    expect(screen.getByText("9876543210")).toBeTruthy();
    expect(screen.getByText("Kolar")).toBeTruthy();
    expect(screen.getByText("SBIN0001234")).toBeTruthy();
    expect(outstandingText()).toContain("321.00");

    // The only event on this page is worth 3,040.82; the balance is 321.00.
    expect(screen.getByText(/The summary covers the whole account/)).toBeTruthy();
    expect(screen.getByText(/A payout is not extra income/)).toBeTruthy();
    expect(screen.getByText(/recovered once, when a payout is finalised/)).toBeTruthy();
    expect(screen.getByText(/2,800\.00 recorded/)).toBeTruthy();
    expect(screen.getByText(/of 25/)).toBeTruthy();
  });

  it("resets to page 1 and sends the selected date and event-type filters", async () => {
    const user = userEvent.setup();
    getLedgerMock.mockResolvedValue(
      page([deliveryEvent], { count: 25, next: "http://api/next" }),
    );
    render(<LedgerScreen initialFarmerId="2" />);
    await screen.findByRole("heading", { name: "Ravi Kumar" });

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(getLedgerMock).toHaveBeenCalledTimes(2));
    expect(lastQuery()).toMatchObject({ page: 2, ordering: "-date" });

    await user.selectOptions(screen.getByLabelText("Event type"), "CORRECTION");
    await waitFor(() => expect(getLedgerMock).toHaveBeenCalledTimes(3));
    expect(lastQuery()).toMatchObject({
      page: 1,
      event_type: "CORRECTION",
      ordering: "-date",
    });

    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-10-01" },
    });
    await waitFor(() => expect(getLedgerMock).toHaveBeenCalledTimes(4));
    expect(lastQuery()).toMatchObject({
      page: 1,
      from: "2026-10-01",
      event_type: "CORRECTION",
    });
  });

  it("explains an empty history and clears an empty filter window", async () => {
    const user = userEvent.setup();
    getLedgerMock.mockResolvedValue(page([]));
    render(<LedgerScreen initialFarmerId="2" />);

    expect(await screen.findByText(/No ledger activity yet/)).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("Event type"), "PAYOUT");
    await waitFor(() =>
      expect(screen.getByText(/No ledger events match this date window/)).toBeTruthy(),
    );

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() =>
      expect(screen.getByText(/No ledger activity yet/)).toBeTruthy(),
    );
    expect(lastQuery()).toMatchObject({
      page: 1,
      event_type: undefined,
      from: undefined,
      to: undefined,
    });
  });

  it("surfaces an API error without inventing a summary", async () => {
    getLedgerMock.mockRejectedValue(
      new ApiError({
        status: 404,
        code: "farmer_not_found",
        message: "Farmer 2 was not found.",
        requestId: "req-ledger-1",
        method: "GET",
        path: "/farmers/2/ledger/",
      }),
    );
    render(<LedgerScreen initialFarmerId="2" />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("farmer_not_found");
    expect(alert.textContent).toContain("Farmer 2 was not found.");
    expect(screen.queryByText("Outstanding advance")).toBeNull();
  });

  it("renders signed corrections and keeps draft recovery distinct from paid recovery", async () => {
    getLedgerMock.mockResolvedValue(
      page([
        creditEvent,
        debitEvent,
        draftPayoutEvent,
        paidPayoutEvent,
      ]),
    );
    render(<LedgerScreen initialFarmerId="2" />);
    await screen.findByRole("heading", { name: "Ravi Kumar" });

    expect(screen.getByText("Credit to farmer")).toBeTruthy();
    expect(screen.getByText("Debit from farmer")).toBeTruthy();
    expect(screen.getByText("₹-25.00")).toBeTruthy();

    expect(
      screen.getByText("Draft projection - recovery not yet applied."),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Paid. Recovery was applied once at finalisation, not again when paid.",
      ),
    ).toBeTruthy();
    expect(screen.getAllByText("Draft projection").length).toBeGreaterThan(0);
    expect(screen.getByText("Paid and settled")).toBeTruthy();
    expect(screen.getByText(/recovery applied/)).toBeTruthy();
  });

  it("links deliveries, original deliveries and payouts back to this farmer's ledger", async () => {
    const user = userEvent.setup();
    getLedgerMock.mockResolvedValue(
      page([creditEvent, paidPayoutEvent]),
    );
    render(<LedgerScreen initialFarmerId="2" />);
    await screen.findByRole("heading", { name: "Ravi Kumar" });

    await user.click(screen.getByRole("button", { name: "#31" }));
    expect(window.location.hash).toBe(
      "#/deliveries/31?from=ledger&farmer=2",
    );

    await user.click(screen.getByRole("button", { name: "Open delivery" }));
    expect(window.location.hash).toBe(
      "#/deliveries/32?from=ledger&farmer=2",
    );

    await user.click(screen.getByRole("button", { name: "Open payout" }));
    expect(window.location.hash).toBe("#/payouts/8?from=ledger&farmer=2");
  });

  it("refreshes the authoritative balance after financial actions elsewhere", async () => {
    const user = userEvent.setup();
    getLedgerMock
      .mockResolvedValueOnce(
        page([advanceEvent], { summary: summary({ outstanding_advance: "321.00" }) }),
      )
      .mockResolvedValueOnce(
        page([], { summary: summary({ outstanding_advance: "111.00" }) }),
      );
    render(<LedgerScreen initialFarmerId="2" />);

    await screen.findByRole("heading", { name: "Ravi Kumar" });
    expect(outstandingText()).toContain("321.00");

    await user.click(screen.getByRole("button", { name: "Refresh ledger" }));
    await waitFor(() => expect(getLedgerMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(outstandingText()).toContain("111.00"));
  });
});
