// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({
  generatePayout: vi.fn(),
  listPayouts: vi.fn(),
}));

import { ApiError } from "../api/client";
import { generatePayout, listPayouts } from "../api/endpoints";
import type { Farmer, Page, Payout, PayoutGeneration } from "../api/types";
import { PayoutGenerateForm } from "./PayoutGenerateForm";

const generatePayoutMock = vi.mocked(generatePayout);
const listPayoutsMock = vi.mocked(listPayouts);

const farmer: Farmer = {
  id: 2,
  name: "Ravi Kumar",
  phone: "9876543210",
  village: "Kolar",
  bank_reference: "",
  outstanding_advance: "500.00",
  created_at: "2026-05-01T10:00:00+05:30",
};
const farmers = new Map([[farmer.id, farmer]]);

const draft: Payout = {
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
};

function page(results: Payout[]): Page<Payout> {
  return { count: results.length, next: null, previous: null, results };
}

function renderForm() {
  const onGenerated = vi.fn();
  const onChanged = vi.fn();
  render(
    <PayoutGenerateForm
      farmers={farmers}
      onGenerated={onGenerated}
      onChanged={onChanged}
    />,
  );
  return { onGenerated, onChanged };
}

async function chooseFarmer(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText("Farmer"), "2");
}

function chooseWeek(value: string) {
  fireEvent.change(screen.getByLabelText("Business week (any day)"), {
    target: { value },
  });
}

function generateButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /Generate \/ refresh draft/,
  }) as HTMLButtonElement;
}

beforeEach(() => {
  generatePayoutMock.mockReset();
  listPayoutsMock.mockReset();
});

afterEach(cleanup);

describe("PayoutGenerateForm", () => {
  it("shows the Monday–Sunday week and sends the chosen day for API normalisation", async () => {
    const user = userEvent.setup();
    const { onGenerated } = renderForm();
    generatePayoutMock.mockResolvedValue({ payout: draft, reason: null });

    chooseWeek("2026-10-14");
    expect(screen.getByText("12 Oct 2026")).toBeTruthy();
    expect(screen.getByText("18 Oct 2026")).toBeTruthy();
    expect(screen.getAllByText(/Monday–Sunday/).length).toBeGreaterThan(0);

    await chooseFarmer(user);
    await user.click(generateButton());

    expect(generatePayoutMock).toHaveBeenCalledWith({
      farmer: 2,
      week_start: "2026-10-14",
    });
    await waitFor(() => expect(onGenerated).toHaveBeenCalledWith(draft));
  });

  it("follows the documented empty-week response without inventing a payout", async () => {
    const user = userEvent.setup();
    const { onGenerated, onChanged } = renderForm();
    generatePayoutMock.mockResolvedValue({
      payout: null,
      reason: "NO_ELIGIBLE_DELIVERIES",
    });

    chooseWeek("2026-10-14");
    await chooseFarmer(user);
    await user.click(generateButton());

    expect(
      await screen.findByText(/No eligible deliveries in this week/),
    ).toBeTruthy();
    expect(screen.getByText(/no balance changed/)).toBeTruthy();
    expect(onGenerated).not.toHaveBeenCalled();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("sends only one generation while the first is in flight", async () => {
    const user = userEvent.setup();
    const { onGenerated } = renderForm();
    let release: (value: PayoutGeneration) => void = () => {};
    generatePayoutMock.mockReturnValue(
      new Promise<PayoutGeneration>((resolve) => {
        release = resolve;
      }),
    );

    chooseWeek("2026-10-14");
    await chooseFarmer(user);
    const button = generateButton();
    await user.click(button);
    await user.click(button);

    expect(generatePayoutMock).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);

    await act(async () => {
      release({ payout: null, reason: "NO_ELIGIBLE_DELIVERIES" });
    });
    expect(onGenerated).not.toHaveBeenCalled();
  });

  it("explains a settled-week conflict and refreshes the statements", async () => {
    const user = userEvent.setup();
    const { onGenerated, onChanged } = renderForm();
    generatePayoutMock.mockRejectedValue(
      new ApiError({
        status: 409,
        code: "payout_state_error",
        message: "This week already has a finalised payout.",
        method: "POST",
        path: "/payouts/generate/",
        isWrite: true,
        outcome: "rejected",
      }),
    );

    chooseWeek("2026-10-14");
    await chooseFarmer(user);
    await user.click(generateButton());

    expect(
      await screen.findByText(/supplementary draft needs a new unassigned record/),
    ).toBeTruthy();
    expect(onChanged).toHaveBeenCalled();
    expect(onGenerated).not.toHaveBeenCalled();
  });

  it("re-checks the week after an ambiguous network result before retrying", async () => {
    const user = userEvent.setup();
    const { onGenerated } = renderForm();
    generatePayoutMock.mockRejectedValue(
      new ApiError({
        status: 0,
        code: "network_error",
        message: "Could not reach the API.",
        method: "POST",
        path: "/payouts/generate/",
        isWrite: true,
        outcome: "unknown",
      }),
    );
    listPayoutsMock.mockResolvedValue(page([draft]));

    chooseWeek("2026-10-14");
    await chooseFarmer(user);
    await user.click(generateButton());

    await waitFor(() => expect(onGenerated).toHaveBeenCalledWith(draft));
    expect(generatePayoutMock).toHaveBeenCalledTimes(1);
    expect(listPayoutsMock).toHaveBeenCalledWith(
      expect.objectContaining({ farmer: 2, week: "2026-10-14" }),
    );
  });
});
