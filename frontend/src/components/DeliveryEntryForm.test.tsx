// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({ createDelivery: vi.fn() }));
vi.mock("../hooks/useDeliveryPreview", () => ({ useDeliveryPreview: vi.fn() }));

import { ApiError } from "../api/client";
import { createDelivery } from "../api/endpoints";
import type {
  CropGrade,
  Delivery,
  DeliveryPreview,
  Farmer,
} from "../api/types";
import { useDeliveryPreview } from "../hooks/useDeliveryPreview";
import { DeliveryEntryForm } from "./DeliveryEntryForm";

const createDeliveryMock = vi.mocked(createDelivery);
const previewHook = vi.mocked(useDeliveryPreview);

const farmer: Farmer = {
  id: 1,
  name: "Ravi Kumar",
  phone: "9876543210",
  village: "Kot",
  bank_reference: "",
  outstanding_advance: "0.00",
  created_at: "2026-05-01T10:00:00+05:30",
};

const gradeA: CropGrade = {
  id: 10,
  crop: 2,
  crop_name: "Paddy",
  code: "A",
  created_at: "2026-05-01T10:00:00+05:30",
};

const gradeB: CropGrade = {
  id: 11,
  crop: 3,
  crop_name: "Maize",
  code: "B",
  created_at: "2026-05-01T10:00:00+05:30",
};

const farmers = new Map([[farmer.id, farmer]]);
const grades = new Map([
  [gradeA.id, gradeA],
  [gradeB.id, gradeB],
]);

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
  recorded_at: "2026-05-02T09:15:00+05:30",
};

function renderForm(onSaved = vi.fn()) {
  render(
    <DeliveryEntryForm farmers={farmers} grades={grades} onSaved={onSaved} />,
  );
  return onSaved;
}

async function fillValidForm(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText("Farmer"), "1");
  await user.selectOptions(screen.getByLabelText("Crop"), "2");
  await user.selectOptions(screen.getByLabelText("Grade"), "10");
  await user.type(screen.getByLabelText("Gross weight (kg)"), "100.125");
  await user.type(screen.getByLabelText("Moisture %"), "16.00");
}

function valueOf(label: string): string {
  return (screen.getByLabelText(label) as HTMLInputElement | HTMLSelectElement)
    .value;
}

beforeEach(() => {
  createDeliveryMock.mockReset();
  previewHook.mockReset();
  previewHook.mockReturnValue({
    preview: undefined,
    error: undefined,
    loading: false,
  });
});

afterEach(cleanup);

describe("DeliveryEntryForm", () => {
  it("keeps recording disabled until all inputs are valid", async () => {
    const user = userEvent.setup();
    renderForm();

    const record = screen.getByRole("button", { name: "Record delivery" });
    expect((record as HTMLButtonElement).disabled).toBe(true);
    expect(previewHook).toHaveBeenLastCalledWith(null);

    await fillValidForm(user);
    expect((record as HTMLButtonElement).disabled).toBe(false);
  });

  it("requests a preview for exactly the entered values and clears a mismatched grade", async () => {
    const user = userEvent.setup();
    renderForm();
    await fillValidForm(user);

    expect(previewHook).toHaveBeenLastCalledWith(
      expect.objectContaining({
        farmer: 1,
        crop_grade: 10,
        gross_weight_kg: "100.125",
        moisture_percent: "16.00",
      }),
    );

    await user.selectOptions(screen.getByLabelText("Crop"), "3");
    expect(valueOf("Grade")).toBe("");
  });

  it("preserves every input when the save fails and never retries by itself", async () => {
    const user = userEvent.setup();
    createDeliveryMock.mockRejectedValueOnce(
      new ApiError({
        status: 0,
        code: "network_error",
        message: "Network request failed.",
        isWrite: true,
        outcome: "unknown",
      }),
    );
    renderForm();
    await fillValidForm(user);

    await user.click(screen.getByRole("button", { name: "Record delivery" }));

    expect(await screen.findByText(/may or may not have been applied/)).toBeTruthy();
    expect(valueOf("Farmer")).toBe("1");
    expect(valueOf("Crop")).toBe("2");
    expect(valueOf("Grade")).toBe("10");
    expect(valueOf("Gross weight (kg)")).toBe("100.125");
    expect(valueOf("Moisture %")).toBe("16.00");
    expect(createDeliveryMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    expect(createDeliveryMock).toHaveBeenCalledTimes(1);
  });

  it("disables the button while saving and ignores a duplicate submit", async () => {
    const user = userEvent.setup();
    let resolve!: (delivery: Delivery) => void;
    const pending = new Promise<Delivery>((done) => {
      resolve = done;
    });
    createDeliveryMock.mockReturnValue(pending);
    const { container } = render(
      <DeliveryEntryForm farmers={farmers} grades={grades} onSaved={vi.fn()} />,
    );
    await fillValidForm(user);

    await user.click(screen.getByRole("button", { name: "Record delivery" }));

    const saving = screen.getByRole("button", { name: "Recording…" });
    expect((saving as HTMLButtonElement).disabled).toBe(true);
    expect(saving.getAttribute("aria-busy")).toBe("true");

    const form = container.querySelector("form");
    expect(form).toBeTruthy();
    fireEvent.submit(form as HTMLFormElement);
    expect(createDeliveryMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolve(stored);
      await pending;
    });
  });

  it("shows the authoritative stored breakdown and how it differs from the preview", async () => {
    const user = userEvent.setup();
    previewHook.mockReturnValue({
      preview,
      error: undefined,
      loading: false,
    });
    createDeliveryMock.mockResolvedValue(stored);
    const onSaved = renderForm();
    await fillValidForm(user);

    await user.click(screen.getByRole("button", { name: "Record delivery" }));

    expect(await screen.findByText("Recorded delivery #7")).toBeTruthy();
    expect(
      screen.getByRole("group", { name: "Stored delivery breakdown" })
        .textContent,
    ).toContain("₹2,453.00");
    expect(screen.getByText("Stored result differs from the preview.")).toBeTruthy();
    expect(screen.getByText(/Amount change: \+₹49\.06/)).toBeTruthy();
    expect(
      screen.getByText(/Applied price: preview 24\.50 → stored 25\.00/),
    ).toBeTruthy();
    expect(
      screen.getByText(/Price entry: preview #5 → stored #6/),
    ).toBeTruthy();
    expect(onSaved).toHaveBeenCalledWith(stored);

    expect(valueOf("Gross weight (kg)")).toBe("");
    expect(valueOf("Moisture %")).toBe("");
  });

  it("confirms when the stored result matches the preview", async () => {
    const user = userEvent.setup();
    previewHook.mockReturnValue({
      preview,
      error: undefined,
      loading: false,
    });
    createDeliveryMock.mockResolvedValue({
      ...stored,
      applied_price: preview.applied_price,
      price_list_entry: preview.price_list_entry,
      amount: preview.amount,
    });
    renderForm();
    await fillValidForm(user);

    await user.click(screen.getByRole("button", { name: "Record delivery" }));

    expect(
      await screen.findByText("Stored result matches the preview."),
    ).toBeTruthy();
  });

  it("explains a missing price without blocking the form fields", async () => {
    const user = userEvent.setup();
    previewHook.mockReturnValue({
      preview: undefined,
      error: new ApiError({
        status: 422,
        code: "price_not_found",
        message: "No effective price for this grade on that date.",
      }),
      loading: false,
    });
    renderForm();
    await fillValidForm(user);

    expect(
      screen.getByText(/No effective price for this grade on that date/),
    ).toBeTruthy();
    expect(screen.getByText("Preview unavailable")).toBeTruthy();
    expect(valueOf("Gross weight (kg)")).toBe("100.125");
  });
});
