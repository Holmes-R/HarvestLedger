// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({ editDelivery: vi.fn() }));

import { ApiError } from "../api/client";
import { editDelivery } from "../api/endpoints";
import type { CropGrade, Delivery } from "../api/types";
import { DeliveryEditForm } from "./DeliveryEditForm";

const editDeliveryMock = vi.mocked(editDelivery);

const grade: CropGrade = {
  id: 10,
  crop: 2,
  crop_name: "Paddy",
  code: "A",
  created_at: "2026-05-01T10:00:00+05:30",
};

const grades = new Map([[grade.id, grade]]);

const delivery: Delivery = {
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
  applied_price: "24.50",
  price_list_entry: 5,
  amount: "2403.94",
  calculation_version: 1,
  original_delivery: null,
  correction_magnitude: null,
  reason: "",
  payout: null,
  recorded_at: "2026-05-02T09:15:00+05:30",
};

function renderEdit(onSaved = vi.fn()) {
  render(
    <DeliveryEditForm
      delivery={delivery}
      grades={grades}
      onClose={vi.fn()}
      onSaved={onSaved}
    />,
  );
  return onSaved;
}

function valueOf(label: string): string {
  return (screen.getByLabelText(label) as HTMLInputElement | HTMLSelectElement)
    .value;
}

beforeEach(() => {
  editDeliveryMock.mockReset();
});

afterEach(cleanup);

describe("DeliveryEditForm", () => {
  it("prefills the stored inputs and patches only the accepted fields", async () => {
    const user = userEvent.setup();
    editDeliveryMock.mockResolvedValue({ ...delivery, gross_weight_kg: "120.500" });
    const onSaved = renderEdit();

    expect(valueOf("Crop")).toBe("2");
    expect(valueOf("Grade")).toBe("10");
    expect(valueOf("Delivered on")).toBe("2026-05-01");

    const gross = screen.getByLabelText("Gross weight (kg)");
    await user.clear(gross);
    await user.type(gross, "120.500");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(editDeliveryMock).toHaveBeenCalledTimes(1);
    const [id, body] = editDeliveryMock.mock.calls[0];
    expect(id).toBe(7);
    expect(body).toEqual({
      crop_grade: 10,
      delivered_on: "2026-05-01",
      gross_weight_kg: "120.500",
      moisture_percent: "16.00",
    });
    expect(Object.keys(body).sort()).toEqual([
      "crop_grade",
      "delivered_on",
      "gross_weight_kg",
      "moisture_percent",
    ]);
    expect(onSaved).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7, gross_weight_kg: "120.500" }),
    );
  });

  it("keeps the inputs when the server rejects the edit", async () => {
    const user = userEvent.setup();
    editDeliveryMock.mockRejectedValue(
      new ApiError({
        status: 409,
        code: "payout_state_error",
        message: "The payout is finalised.",
      }),
    );
    renderEdit();

    const gross = screen.getByLabelText("Gross weight (kg)");
    await user.clear(gross);
    await user.type(gross, "111.000");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("The payout is finalised.")).toBeTruthy();
    expect(valueOf("Gross weight (kg)")).toBe("111.000");
    expect(valueOf("Moisture %")).toBe("16.00");
  });
});
