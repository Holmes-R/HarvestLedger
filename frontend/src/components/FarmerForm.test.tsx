// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({
  createFarmer: vi.fn(),
  updateFarmer: vi.fn(),
}));

import { ApiError } from "../api/client";
import { createFarmer, updateFarmer } from "../api/endpoints";
import type { Farmer } from "../api/types";
import { FarmerForm } from "./FarmerForm";

const createFarmerMock = vi.mocked(createFarmer);
const updateFarmerMock = vi.mocked(updateFarmer);

const farmer: Farmer = {
  id: 1,
  name: "Ravi Kumar",
  phone: "9876543210",
  village: "Kolar",
  bank_reference: "SBIN0001234",
  outstanding_advance: "321.00",
  created_at: "2026-05-01T10:00:00+05:30",
};

beforeEach(() => {
  createFarmerMock.mockReset();
  updateFarmerMock.mockReset();
});

afterEach(cleanup);

describe("FarmerForm", () => {
  it("creates a farmer without sending the server-owned outstanding balance", async () => {
    const user = userEvent.setup();
    createFarmerMock.mockResolvedValue({ ...farmer, outstanding_advance: "0.00" });
    const onSaved = vi.fn();
    render(<FarmerForm onClose={vi.fn()} onSaved={onSaved} />);

    await user.type(screen.getByLabelText("Name"), "Ravi Kumar");
    await user.type(screen.getByLabelText("Phone"), "9876543210");
    await user.type(screen.getByLabelText("Village"), "Kolar");
    await user.type(screen.getByLabelText("Bank reference (optional)"), "SBIN0001234");
    await user.click(screen.getByRole("button", { name: "Create farmer" }));

    expect(createFarmerMock).toHaveBeenCalledWith({
      name: "Ravi Kumar",
      phone: "9876543210",
      village: "Kolar",
      bank_reference: "SBIN0001234",
    });
    expect(createFarmerMock.mock.calls[0][0]).not.toHaveProperty(
      "outstanding_advance",
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("shows the stored balance read-only when editing and patches permitted fields", async () => {
    const user = userEvent.setup();
    updateFarmerMock.mockResolvedValue({ ...farmer, village: "Mandya" });
    render(<FarmerForm farmer={farmer} onClose={vi.fn()} onSaved={vi.fn()} />);

    expect(screen.getByText(/321\.00/)).toBeTruthy();
    expect(screen.getByText(/server-owned and read-only/)).toBeTruthy();

    await user.clear(screen.getByLabelText("Village"));
    await user.type(screen.getByLabelText("Village"), "Mandya");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(updateFarmerMock).toHaveBeenCalledWith(1, {
      name: "Ravi Kumar",
      phone: "9876543210",
      village: "Mandya",
      bank_reference: "SBIN0001234",
    });
    expect(updateFarmerMock.mock.calls[0][1]).not.toHaveProperty(
      "outstanding_advance",
    );
  });

  it("maps a rejected phone onto its field and preserves the values", async () => {
    const user = userEvent.setup();
    createFarmerMock.mockRejectedValue(
      new ApiError({
        status: 400,
        code: "invalid",
        message: "Invalid farmer.",
        details: {
          phone: [
            { code: "invalid", message: "Enter a valid Indian mobile number." },
          ],
        },
        requestId: "req-farmer-1234",
      }),
    );
    render(<FarmerForm onClose={vi.fn()} onSaved={vi.fn()} />);

    await user.type(screen.getByLabelText("Name"), "Asha");
    await user.type(screen.getByLabelText("Phone"), "9000000001");
    await user.type(screen.getByLabelText("Village"), "Kolar");
    await user.click(screen.getByRole("button", { name: "Create farmer" }));

    expect(await screen.findByText(/req-farmer-1234/)).toBeTruthy();
    expect(
      screen.getByLabelText("Phone").getAttribute("aria-invalid"),
    ).toBe("true");
    expect(
      (screen.getByLabelText("Name") as HTMLInputElement).value,
    ).toBe("Asha");
    expect(
      (screen.getByLabelText("Village") as HTMLInputElement).value,
    ).toBe("Kolar");
  });
});
