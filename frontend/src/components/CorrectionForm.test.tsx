// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({
  createCorrection: vi.fn(),
  createDeliveryCorrection: vi.fn(),
}));

import { ApiError } from "../api/client";
import {
  createCorrection,
  createDeliveryCorrection,
} from "../api/endpoints";
import type { Correction, Farmer } from "../api/types";
import { CorrectionForm } from "./CorrectionForm";

const createCorrectionMock = vi.mocked(createCorrection);
const createDeliveryCorrectionMock = vi.mocked(createDeliveryCorrection);

const farmer: Farmer = {
  id: 1,
  name: "Ravi Kumar",
  phone: "9876543210",
  village: "Kolar",
  bank_reference: "",
  outstanding_advance: "321.00",
  created_at: "2026-05-01T10:00:00+05:30",
};

const correction: Correction = {
  id: 88,
  farmer: 1,
  kind: "CREDIT_NOTE",
  original_delivery: 31,
  correction_magnitude: "50.25",
  reason: "quality allowance",
  accounting_date: "2026-10-20",
  amount: "50.25",
  payout: null,
  recorded_at: "2026-10-20T10:00:00+05:30",
};

beforeEach(() => {
  createCorrectionMock.mockReset();
  createDeliveryCorrectionMock.mockReset();
});

afterEach(cleanup);

describe("CorrectionForm", () => {
  it("states the linked original/farmer and posts a positive magnitude with the kind's sign", async () => {
    const user = userEvent.setup();
    createDeliveryCorrectionMock.mockResolvedValue(correction);
    const onSaved = vi.fn();
    render(
      <CorrectionForm
        deliveryId={31}
        original={{ id: 31, farmer: 1 }}
        farmer={farmer}
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Correct delivery #31" }),
    ).toBeTruthy();
    expect(screen.getAllByText(/#31/).length).toBeGreaterThan(0);
    expect(screen.getByText("Ravi Kumar")).toBeTruthy();
    expect(screen.getByText(/original delivery snapshot/)).toBeTruthy();

    await user.type(screen.getByLabelText("Magnitude (INR)"), "50.25");
    await user.type(screen.getByLabelText("Reason"), "quality allowance");
    await user.click(screen.getByRole("button", { name: "Record note" }));

    expect(createDeliveryCorrectionMock).toHaveBeenCalledWith(31, {
      kind: "CREDIT_NOTE",
      magnitude: "50.25",
      reason: "quality allowance",
    });
    expect(createDeliveryCorrectionMock.mock.calls[0][1]).not.toHaveProperty(
      "original_delivery",
    );
    expect(onSaved).toHaveBeenCalledWith(correction);
  });

  it("supports a debit note without letting the user type a sign", async () => {
    const user = userEvent.setup();
    createDeliveryCorrectionMock.mockResolvedValue({
      ...correction,
      kind: "DEBIT_NOTE",
      amount: "-50.25",
    });
    render(
      <CorrectionForm
        deliveryId={31}
        original={{ id: 31, farmer: 1 }}
        farmer={farmer}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Kind"), "DEBIT_NOTE");
    await user.type(screen.getByLabelText("Magnitude (INR)"), "-50.25");
    expect(screen.getByText("Must be positive.")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Record note" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    await user.clear(screen.getByLabelText("Magnitude (INR)"));
    await user.type(screen.getByLabelText("Magnitude (INR)"), "50.25");
    await user.type(screen.getByLabelText("Reason"), "short weight");
    await user.click(screen.getByRole("button", { name: "Record note" }));

    expect(createDeliveryCorrectionMock).toHaveBeenCalledWith(31, {
      kind: "DEBIT_NOTE",
      magnitude: "50.25",
      reason: "short weight",
    });
  });

  it("shows field errors and preserves the inputs when the API rejects the note", async () => {
    const user = userEvent.setup();
    createDeliveryCorrectionMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "not_positive",
        message: "Magnitude must be positive.",
        details: {
          magnitude: [
            { code: "not_positive", message: "Magnitude must be positive." },
          ],
        },
        requestId: "req-correction-1234",
      }),
    );
    render(
      <CorrectionForm
        deliveryId={31}
        original={{ id: 31, farmer: 1 }}
        farmer={farmer}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("Magnitude (INR)"), "50.25");
    await user.type(screen.getByLabelText("Reason"), "quality allowance");
    await user.click(screen.getByRole("button", { name: "Record note" }));

    expect(await screen.findByText(/req-correction-1234/)).toBeTruthy();
    expect(
      screen.getByLabelText("Magnitude (INR)").getAttribute("aria-invalid"),
    ).toBe("true");
    expect(
      (screen.getByLabelText("Magnitude (INR)") as HTMLInputElement).value,
    ).toBe("50.25");
    expect((screen.getByLabelText("Reason") as HTMLInputElement).value).toBe(
      "quality allowance",
    );
  });
});
