// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({ createAdvance: vi.fn() }));

import { ApiError } from "../api/client";
import { createAdvance } from "../api/endpoints";
import type { Advance, Farmer } from "../api/types";
import { AdvanceForm } from "./AdvanceForm";

const createAdvanceMock = vi.mocked(createAdvance);

const farmer: Farmer = {
  id: 1,
  name: "Ravi Kumar",
  phone: "9876543210",
  village: "Kolar",
  bank_reference: "",
  outstanding_advance: "321.00",
  created_at: "2026-05-01T10:00:00+05:30",
};

const advance: Advance = {
  id: 9,
  farmer: 1,
  amount: "500.00",
  given_on: "2026-05-02",
  created_at: "2026-05-02T09:00:00+05:30",
};

beforeEach(() => {
  createAdvanceMock.mockReset();
  window.location.hash = "#/ledger?farmer=1";
});

afterEach(cleanup);

describe("AdvanceForm", () => {
  it("shows the server-owned balance read-only and sends only the three inputs", async () => {
    const user = userEvent.setup();
    createAdvanceMock.mockResolvedValue(advance);
    const onSaved = vi.fn();
    render(
      <AdvanceForm
        farmers={[farmer]}
        defaultFarmerId={1}
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );

    expect(screen.getByText(/Current outstanding advance/)).toBeTruthy();
    expect(screen.getAllByText(/321\.00/).length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText("Amount (INR)"), "500.00");
    fireEvent.change(screen.getByLabelText("Given on"), {
      target: { value: "2026-05-02" },
    });
    await user.click(screen.getByRole("button", { name: "Post advance" }));

    expect(createAdvanceMock).toHaveBeenCalledWith({
      farmer: 1,
      amount: "500.00",
      given_on: "2026-05-02",
    });
    expect(createAdvanceMock.mock.calls[0][0]).not.toHaveProperty(
      "outstanding_advance",
    );
    expect(onSaved).toHaveBeenCalledWith(advance);
  });

  it("preserves the amount and farmer after a failed advance", async () => {
    const user = userEvent.setup();
    createAdvanceMock.mockRejectedValue(
      new ApiError({
        status: 400,
        code: "not_positive",
        message: "Amount must be positive.",
        details: {
          amount: [{ code: "not_positive", message: "Enter an amount above zero." }],
        },
        requestId: "req-advance-1234",
      }),
    );
    render(
      <AdvanceForm
        farmers={[farmer]}
        defaultFarmerId={1}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("Amount (INR)"), "500.00");
    await user.click(screen.getByRole("button", { name: "Post advance" }));

    expect(await screen.findByText(/req-advance-1234/)).toBeTruthy();
    expect(
      (screen.getByLabelText("Amount (INR)") as HTMLInputElement).value,
    ).toBe("500.00");
    expect(
      (screen.getByLabelText("Farmer") as HTMLSelectElement).value,
    ).toBe("1");
    expect(
      screen.getByLabelText("Amount (INR)").getAttribute("aria-invalid"),
    ).toBe("true");
    expect(createAdvanceMock).toHaveBeenCalledTimes(1);
  });

  it("ignores a second submit while the first advance is in flight", async () => {
    const user = userEvent.setup();
    let resolve!: (value: Advance) => void;
    const pending = new Promise<Advance>((done) => {
      resolve = done;
    });
    createAdvanceMock.mockReturnValue(pending);
    const { container } = render(
      <AdvanceForm
        farmers={[farmer]}
        defaultFarmerId={1}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("Amount (INR)"), "500.00");
    await user.click(screen.getByRole("button", { name: "Post advance" }));
    expect(
      (screen.getByRole("button", { name: "Posting..." }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    const form = container.querySelector("form");
    fireEvent.submit(form as HTMLFormElement);
    expect(createAdvanceMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolve(advance);
      await pending;
    });
  });
});
