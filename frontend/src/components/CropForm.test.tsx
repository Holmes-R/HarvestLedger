// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/endpoints", () => ({
  createCrop: vi.fn(),
  updateCrop: vi.fn(),
}));

import { ApiError } from "../api/client";
import { createCrop, updateCrop } from "../api/endpoints";
import type { Crop } from "../api/types";
import { CropForm } from "./CropForm";

const createCropMock = vi.mocked(createCrop);
const updateCropMock = vi.mocked(updateCrop);

const crop: Crop = {
  id: 3,
  name: "Paddy",
  moisture_threshold: "14.00",
  max_moisture: "20.00",
  allowed_grades: [
    { id: 10, code: "A" },
    { id: 11, code: "B" },
  ],
  created_at: "2026-05-01T10:00:00+05:30",
};

function valueOf(label: string): string {
  return (screen.getByLabelText(label) as HTMLInputElement).value;
}

beforeEach(() => {
  createCropMock.mockReset();
  updateCropMock.mockReset();
});

afterEach(cleanup);

describe("CropForm", () => {
  it("rejects an out-of-range moisture configuration before calling the API", async () => {
    const user = userEvent.setup();
    render(<CropForm onClose={vi.fn()} onSaved={vi.fn()} />);

    await user.type(screen.getByLabelText("Name"), "Paddy");
    await user.type(screen.getByLabelText("Moisture threshold %"), "-1");
    await user.type(screen.getByLabelText("Max moisture %"), "101");

    expect(screen.getByText("Must be at least 0.")).toBeTruthy();
    expect(screen.getByText("Must be at most 100.")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Create crop" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(createCropMock).not.toHaveBeenCalled();
  });

  it("keeps the entered configuration when the API rejects the bounds", async () => {
    const user = userEvent.setup();
    createCropMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "invalid_moisture_bounds",
        message: "Moisture configuration is invalid.",
        details: {
          max_moisture: [
            {
              code: "invalid_moisture_bounds",
              message: "0 <= moisture_threshold <= max_moisture <= 100.",
            },
          ],
        },
        requestId: "req-crop-1234",
      }),
    );
    render(<CropForm onClose={vi.fn()} onSaved={vi.fn()} />);

    await user.type(screen.getByLabelText("Name"), "Paddy");
    await user.type(screen.getByLabelText("Moisture threshold %"), "14");
    await user.type(screen.getByLabelText("Max moisture %"), "20");
    await user.type(screen.getByLabelText("Allowed grades"), "A, B");
    await user.click(screen.getByRole("button", { name: "Create crop" }));

    expect(await screen.findByText(/req-crop-1234/)).toBeTruthy();
    expect(
      screen.getByLabelText("Max moisture %").getAttribute("aria-invalid"),
    ).toBe("true");
    expect(valueOf("Name")).toBe("Paddy");
    expect(valueOf("Moisture threshold %")).toBe("14");
    expect(valueOf("Max moisture %")).toBe("20");
    expect(valueOf("Allowed grades")).toBe("A, B");
  });

  it("accepts zero and the exact upper bound", async () => {
    const user = userEvent.setup();
    createCropMock.mockResolvedValue({
      ...crop,
      moisture_threshold: "0",
      max_moisture: "100.00",
    });
    render(<CropForm onClose={vi.fn()} onSaved={vi.fn()} />);

    await user.type(screen.getByLabelText("Name"), "Maize");
    await user.type(screen.getByLabelText("Moisture threshold %"), "0");
    await user.type(screen.getByLabelText("Max moisture %"), "100.00");
    await user.click(screen.getByRole("button", { name: "Create crop" }));

    expect(createCropMock).toHaveBeenCalledWith({
      name: "Maize",
      moisture_threshold: "0",
      max_moisture: "100.00",
    });
  });

  it("updates a crop with only the accepted fields and grade codes", async () => {
    const user = userEvent.setup();
    updateCropMock.mockResolvedValue({
      ...crop,
      allowed_grades: [{ id: 10, code: "A" }],
    });
    const onSaved = vi.fn();
    render(<CropForm crop={crop} onClose={vi.fn()} onSaved={onSaved} />);

    await user.clear(screen.getByLabelText("Allowed grades"));
    await user.type(screen.getByLabelText("Allowed grades"), "A");
    await user.click(screen.getByRole("button", { name: "Save crop" }));

    expect(updateCropMock).toHaveBeenCalledWith(3, {
      name: "Paddy",
      moisture_threshold: "14.00",
      max_moisture: "20.00",
      allowed_grades: ["A"],
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
  });
});
