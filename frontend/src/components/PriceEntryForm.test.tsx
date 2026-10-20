// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({ createPriceEntry: vi.fn() }));

import { ApiError } from "../api/client";
import { createPriceEntry } from "../api/endpoints";
import type { CropGrade, PriceListEntry } from "../api/types";
import { PriceEntryForm } from "./PriceEntryForm";

const createPriceEntryMock = vi.mocked(createPriceEntry);

const gradeA: CropGrade = {
  id: 10,
  crop: 2,
  crop_name: "Paddy",
  code: "A",
  created_at: "2026-05-01T10:00:00+05:30",
};
const gradeB: CropGrade = {
  id: 11,
  crop: 2,
  crop_name: "Paddy",
  code: "B",
  created_at: "2026-05-01T10:00:00+05:30",
};
const grades = new Map([
  [gradeA.id, gradeA],
  [gradeB.id, gradeB],
]);

const entry: PriceListEntry = {
  id: 5,
  crop_grade: 10,
  crop_grade_code: "A",
  crop: 2,
  crop_name: "Paddy",
  price_per_kg: "24.50",
  effective_from: "2026-05-01",
  created_at: "2026-04-20T10:00:00+05:30",
};

function renderForm(onSaved = vi.fn()) {
  const view = render(
    <PriceEntryForm grades={grades} onSaved={onSaved} />,
  );
  return { ...view, onSaved };
}

function valueOf(label: string): string {
  return (screen.getByLabelText(label) as HTMLInputElement | HTMLSelectElement).value;
}

async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText("Crop"), "2");
  await user.selectOptions(screen.getByLabelText("Grade"), "10");
  await user.type(screen.getByLabelText("Rate (₹/kg)"), "24.50");
  fireEvent.change(screen.getByLabelText("Effective from"), {
    target: { value: "2026-05-01" },
  });
}

beforeEach(() => {
  createPriceEntryMock.mockReset();
});

afterEach(cleanup);

describe("PriceEntryForm", () => {
  it("keeps adding disabled until the entry is valid and rejects excess precision", async () => {
    const user = userEvent.setup();
    renderForm();

    const add = screen.getByRole("button", { name: "Add price" });
    expect((add as HTMLButtonElement).disabled).toBe(true);

    await user.selectOptions(screen.getByLabelText("Crop"), "2");
    await user.selectOptions(screen.getByLabelText("Grade"), "10");
    await user.type(screen.getByLabelText("Rate (₹/kg)"), "24.555");

    expect((add as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/At most 2 decimal places/)).toBeTruthy();
  });

  it("posts exactly the four append-only fields and keeps the grade for the next entry", async () => {
    const user = userEvent.setup();
    createPriceEntryMock.mockResolvedValue(entry);
    const { onSaved } = renderForm();
    await fillValid(user);

    await user.click(screen.getByRole("button", { name: "Add price" }));

    expect(createPriceEntryMock).toHaveBeenCalledTimes(1);
    const body = createPriceEntryMock.mock.calls[0][0];
    expect(body).toEqual({
      crop: 2,
      grade: 10,
      price_per_kg: "24.50",
      effective_from: "2026-05-01",
    });
    expect(Object.keys(body).sort()).toEqual([
      "crop",
      "effective_from",
      "grade",
      "price_per_kg",
    ]);
    expect(onSaved).toHaveBeenCalledWith(entry);
    expect(valueOf("Rate (₹/kg)")).toBe("");
    expect(valueOf("Crop")).toBe("2");
    expect(valueOf("Grade")).toBe("10");
  });

  it("explains how back-dated, current and future effective dates apply", async () => {
    renderForm();

    expect(screen.getByText(/on or after today/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Effective from"), {
      target: { value: "2020-01-01" },
    });
    expect(screen.getByText(/Back-dated/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Effective from"), {
      target: { value: "2099-01-01" },
    });
    expect(screen.getByText(/Future-dated/)).toBeTruthy();
  });

  it("reports a duplicate effective-date conflict as a field error and does not save", async () => {
    const user = userEvent.setup();
    createPriceEntryMock.mockRejectedValue(
      new ApiError({
        status: 409,
        code: "price_already_exists",
        message: "A price already exists.",
      }),
    );
    const { onSaved } = renderForm();
    await fillValid(user);

    await user.click(screen.getByRole("button", { name: "Add price" }));

    expect(await screen.findByText(/choose a different date/)).toBeTruthy();
    expect(screen.getByText("Not added.")).toBeTruthy();
    expect(screen.getByLabelText("Effective from").getAttribute("aria-invalid")).toBe(
      "true",
    );
    expect(valueOf("Rate (₹/kg)")).toBe("24.50");
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("reports an unallowed grade on the grade field", async () => {
    const user = userEvent.setup();
    createPriceEntryMock.mockRejectedValue(
      new ApiError({ status: 422, code: "grade_not_allowed", message: "no" }),
    );
    renderForm();
    await fillValid(user);

    await user.click(screen.getByRole("button", { name: "Add price" }));

    expect(
      await screen.findByText(/not allowed for the selected crop/),
    ).toBeTruthy();
    expect(screen.getByLabelText("Grade").getAttribute("aria-invalid")).toBe("true");
  });

  it("ignores a duplicate submit while the first is in flight", async () => {
    const user = userEvent.setup();
    let resolve!: (value: PriceListEntry) => void;
    const pending = new Promise<PriceListEntry>((done) => {
      resolve = done;
    });
    createPriceEntryMock.mockReturnValue(pending);
    const { container } = renderForm();
    await fillValid(user);

    await user.click(screen.getByRole("button", { name: "Add price" }));
    const adding = screen.getByRole("button", { name: "Adding…" });
    expect((adding as HTMLButtonElement).disabled).toBe(true);

    const form = container.querySelector("form");
    fireEvent.submit(form as HTMLFormElement);
    expect(createPriceEntryMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolve(entry);
      await pending;
    });
  });
});
