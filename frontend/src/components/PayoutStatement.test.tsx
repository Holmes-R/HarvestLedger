// @vitest-environment jsdom
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({
  finalisePayout: vi.fn(),
  markPayoutPaid: vi.fn(),
  getPayout: vi.fn(),
}));

import { ApiError } from "../api/client";
import { finalisePayout, getPayout, markPayoutPaid } from "../api/endpoints";
import type { Delivery, Payout } from "../api/types";
import { PayoutStatement } from "./PayoutStatement";

const finaliseMock = vi.mocked(finalisePayout);
const markPaidMock = vi.mocked(markPayoutPaid);
const getPayoutMock = vi.mocked(getPayout);

const procurement: Delivery = {
  id: 31,
  farmer: 2,
  kind: "PROCUREMENT",
  crop_grade: 10,
  delivered_on: "2026-10-13",
  accounting_date: "2026-10-13",
  gross_weight_kg: "120.500",
  moisture_percent: "12.00",
  threshold_used: "14.00",
  deduction_percent: "2.00",
  deduction_kg: "2.41000",
  net_kg: "118.09000",
  applied_price: "25.75",
  price_list_entry: 3,
  amount: "3040.82",
  calculation_version: 1,
  original_delivery: null,
  correction_magnitude: null,
  reason: "",
  payout: 7,
  recorded_at: "2026-10-13T10:00:00+05:30",
};

const creditNote: Delivery = {
  ...procurement,
  id: 32,
  kind: "CREDIT_NOTE",
  crop_grade: null,
  delivered_on: null,
  accounting_date: "2026-10-18",
  gross_weight_kg: null,
  moisture_percent: null,
  threshold_used: null,
  deduction_percent: "0.00",
  deduction_kg: "0.00000",
  net_kg: "0.00000",
  applied_price: null,
  price_list_entry: null,
  amount: "100.00",
  original_delivery: 31,
  correction_magnitude: "100.00",
  reason: "Weight recheck",
};

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
    deliveries: [procurement],
    created_at: "2026-10-19T10:00:00+05:30",
    finalised_at: null,
    paid_at: null,
    ...overrides,
  };
}

function renderStatement(
  overrides: Partial<Payout> = {},
  options: {
    statementSet?: Payout[];
    outstandingAdvance?: string;
  } = {},
) {
  const value = payout(overrides);
  const onChanged = vi.fn();
  const onOpenPayout = vi.fn();
  const onOpenDelivery = vi.fn();
  const onBack = vi.fn();
  render(
    <PayoutStatement
      payout={value}
      statementSet={options.statementSet ?? [value]}
      outstandingAdvance={options.outstandingAdvance ?? "500.00"}
      onChanged={onChanged}
      onOpenPayout={onOpenPayout}
      onOpenDelivery={onOpenDelivery}
      onBack={onBack}
    />,
  );
  return { payout: value, onChanged, onOpenPayout, onOpenDelivery, onBack };
}

function networkError(): ApiError {
  return new ApiError({
    status: 0,
    code: "network_error",
    message: "Could not reach the API.",
    method: "POST",
    path: "/payouts/7/finalise/",
    isWrite: true,
    outcome: "unknown",
  });
}

function stateConflict(): ApiError {
  return new ApiError({
    status: 409,
    code: "payout_state_error",
    message: "Only a draft payout can be finalised; this payout is FINALISED.",
    method: "POST",
    path: "/payouts/7/finalise/",
    isWrite: true,
    outcome: "rejected",
  });
}

beforeEach(() => {
  finaliseMock.mockReset();
  markPaidMock.mockReset();
  getPayoutMock.mockReset();
});

afterEach(cleanup);

describe("PayoutStatement", () => {
  it("presents a Draft as a read-only projection that has not recovered anything", () => {
    renderStatement();

    expect(screen.getByText("Estimated draft recovery")).toBeTruthy();
    expect(screen.getByText("Estimated draft net")).toBeTruthy();
    expect(screen.getByText("Not yet applied")).toBeTruthy();
    expect(screen.getByText(/A Draft has not reduced/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Finalise" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Mark paid" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("spinbutton")).toBeNull();
  });

  it("confirms the farmer, week and financial effect before finalising", async () => {
    const user = userEvent.setup();
    const { onChanged } = renderStatement();
    finaliseMock.mockResolvedValue(
      payout({
        status: "FINALISED",
        advance_deduction: "300.00",
        net_amount: "700.00",
        finalised_at: "2026-10-20T10:00:00+05:30",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Finalise" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Ravi Kumar")).toBeTruthy();
    expect(within(dialog).getByText("12 Oct 2026")).toBeTruthy();
    expect(within(dialog).getByText("18 Oct 2026")).toBeTruthy();
    expect(within(dialog).getByText(/min\(outstanding advance, 30% of gross\)/))
      .toBeTruthy();
    expect(within(dialog).getAllByText("₹1,000.00").length).toBeGreaterThan(0);

    await user.click(within(dialog).getByRole("button", { name: "Finalise" }));

    await waitFor(() => expect(finaliseMock).toHaveBeenCalledWith(7));
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByText(/Statement #7 is finalised/)).toBeTruthy();
    expect(screen.getByText("Advance recovered")).toBeTruthy();
    expect(screen.getByText("₹300.00")).toBeTruthy();
    expect(screen.getByText("₹700.00")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Mark paid" })).toBeTruthy();
  });

  it("ignores a second finalise click while the first is in flight", async () => {
    const user = userEvent.setup();
    renderStatement();
    let release: (value: Payout) => void = () => {};
    finaliseMock.mockReturnValue(
      new Promise<Payout>((resolve) => {
        release = resolve;
      }),
    );

    await user.click(screen.getByRole("button", { name: "Finalise" }));
    const dialog = screen.getByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", {
      name: "Finalise",
    }) as HTMLButtonElement;
    await user.click(confirm);
    await user.click(confirm);

    expect(finaliseMock).toHaveBeenCalledTimes(1);
    expect(confirm.disabled).toBe(true);
    expect(within(dialog).getByRole("button", { name: "Finalising…" })).toBeTruthy();

    await act(async () => {
      release(payout({ status: "FINALISED" }));
    });
  });

  it("shows a stale-state conflict, refreshes and keeps the statement visible", async () => {
    const user = userEvent.setup();
    const { onChanged } = renderStatement();
    finaliseMock.mockRejectedValue(stateConflict());

    await user.click(screen.getByRole("button", { name: "Finalise" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finalise",
      }),
    );

    expect(
      await screen.findByText(/The statement changed on the server/),
    ).toBeTruthy();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText(/Only a draft payout can be finalised/)).toBeTruthy();
    expect(screen.getByText("Ravi Kumar")).toBeTruthy();
    expect(onChanged).toHaveBeenCalled();
  });

  it("re-fetches an ambiguous finalisation instead of retrying it", async () => {
    const user = userEvent.setup();
    const { onChanged } = renderStatement();
    finaliseMock.mockRejectedValue(networkError());
    getPayoutMock.mockResolvedValue(payout({ status: "FINALISED" }));

    await user.click(screen.getByRole("button", { name: "Finalise" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finalise",
      }),
    );

    await waitFor(() => expect(getPayoutMock).toHaveBeenCalledWith(7));
    expect(
      await screen.findByText(/did not prevent the change/),
    ).toBeTruthy();
    expect(finaliseMock).toHaveBeenCalledTimes(1);
    expect(onChanged).toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Mark paid" })).toBeTruthy();
  });

  it("keeps the dialog open when an ambiguous finalisation did not apply", async () => {
    const user = userEvent.setup();
    renderStatement();
    finaliseMock.mockRejectedValue(networkError());
    getPayoutMock.mockResolvedValue(payout({ status: "DRAFT" }));

    await user.click(screen.getByRole("button", { name: "Finalise" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Finalise",
      }),
    );

    expect(
      await screen.findByText(/still shows the previous status/),
    ).toBeTruthy();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(finaliseMock).toHaveBeenCalledTimes(1);
  });

  it("offers Mark paid only for a Finalised statement and settles it", async () => {
    const user = userEvent.setup();
    const { onChanged } = renderStatement({
      status: "FINALISED",
      advance_deduction: "300.00",
      net_amount: "700.00",
      finalised_at: "2026-10-20T10:00:00+05:30",
    });
    markPaidMock.mockResolvedValue(
      payout({
        status: "PAID",
        advance_deduction: "300.00",
        net_amount: "700.00",
        finalised_at: "2026-10-20T10:00:00+05:30",
        paid_at: "2026-10-21T10:00:00+05:30",
      }),
    );

    expect(screen.queryByRole("button", { name: "Finalise" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Mark paid" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Net payable")).toBeTruthy();
    expect(within(dialog).getByText("₹700.00")).toBeTruthy();

    await user.click(within(dialog).getByRole("button", { name: "Mark paid" }));

    await waitFor(() => expect(markPaidMock).toHaveBeenCalledWith(7));
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByText(/Statement #7 is marked paid/)).toBeTruthy();
    expect(screen.getByText(/Settled — read-only/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Mark paid" })).toBeNull();
  });

  it("shows a paid statement as read-only", () => {
    renderStatement({
      status: "PAID",
      advance_deduction: "300.00",
      net_amount: "700.00",
      finalised_at: "2026-10-20T10:00:00+05:30",
      paid_at: "2026-10-21T10:00:00+05:30",
    });

    expect(screen.getByText(/Settled — read-only/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Finalise" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Mark paid" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("Net payable")).toBeTruthy();
  });

  it("labels a later Draft as a supplementary payout and links the earlier one", async () => {
    const user = userEvent.setup();
    const current = payout({});
    const earlier = payout({ id: 4, status: "FINALISED" });
    const { onOpenPayout } = renderStatement(current, {
      statementSet: [earlier, current],
    });

    expect(screen.getByText("Supplementary payout.")).toBeTruthy();
    expect(screen.getByText(/applies recovery again/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "#4 (Finalised)" }));
    expect(onOpenPayout).toHaveBeenCalledWith(4);
  });

  it("explains a non-positive statement without blocking Mark paid", () => {
    renderStatement({
      status: "FINALISED",
      gross_amount: "-50.00",
      advance_deduction: "0.00",
      net_amount: "-50.00",
    });

    expect(screen.getByText(/pays it as-is/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Mark paid" })).toBeTruthy();
  });

  it("shows stored breakdowns and links a correction to its original delivery", async () => {
    const user = userEvent.setup();
    const { onOpenDelivery } = renderStatement({
      deliveries: [procurement, creditNote],
    });

    expect(screen.getByText("120.500 kg")).toBeTruthy();
    expect(screen.getAllByText(/₹25\.75/).length).toBeGreaterThan(0);
    expect(screen.getByText("/kg")).toBeTruthy();
    expect(screen.getByText("118.09000 kg")).toBeTruthy();
    expect(screen.getByText("Weight recheck")).toBeTruthy();
    expect(screen.getAllByText("₹100.00").length).toBeGreaterThan(0);

    const originalLinks = screen.getAllByRole("button", { name: "#31" });
    await user.click(originalLinks[originalLinks.length - 1]);
    expect(onOpenDelivery).toHaveBeenCalledWith(31);
  });
});
