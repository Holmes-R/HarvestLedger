// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/lookups", () => ({ loadGradeMap: vi.fn() }));
vi.mock("../api/endpoints", () => ({
  listPrices: vi.fn(),
  createPriceEntry: vi.fn(),
}));

import { ApiError } from "../api/client";
import { createPriceEntry, listPrices } from "../api/endpoints";
import { loadGradeMap } from "../api/lookups";
import type { CropGrade, Page, PriceListEntry } from "../api/types";
import { PricesScreen } from "./PricesScreen";

const loadGradeMapMock = vi.mocked(loadGradeMap);
const listPricesMock = vi.mocked(listPrices);
const createPriceEntryMock = vi.mocked(createPriceEntry);

function grade(id: number, crop: number, cropName: string, code: string): CropGrade {
  return {
    id,
    crop,
    crop_name: cropName,
    code,
    created_at: "2026-05-01T10:00:00+05:30",
  };
}

const gradeMap = new Map([
  [10, grade(10, 2, "Paddy", "A")],
  [11, grade(11, 2, "Paddy", "B")],
  [12, grade(12, 3, "Maize", "A")],
]);

function entry(overrides: Partial<PriceListEntry>): PriceListEntry {
  return {
    id: 5,
    crop_grade: 10,
    crop_grade_code: "A",
    crop: 2,
    crop_name: "Paddy",
    price_per_kg: "24.50",
    effective_from: "2026-04-01",
    created_at: "2026-03-20T10:00:00+05:30",
    ...overrides,
  };
}

function page(results: PriceListEntry[]): Page<PriceListEntry> {
  return { count: results.length, next: null, previous: null, results };
}

function lastQuery(): Record<string, unknown> {
  const calls = listPricesMock.mock.calls;
  return calls[calls.length - 1][0] as Record<string, unknown>;
}

async function waitForFilters() {
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Filter by crop") as HTMLSelectElement).disabled,
    ).toBe(false),
  );
}

beforeEach(() => {
  loadGradeMapMock.mockReset();
  listPricesMock.mockReset();
  createPriceEntryMock.mockReset();
  loadGradeMapMock.mockResolvedValue(gradeMap);
  listPricesMock.mockResolvedValue(page([entry({})]));
});

afterEach(cleanup);

describe("PricesScreen", () => {
  it("shows effective-dated history newest-first with exact decimal rates", async () => {
    render(<PricesScreen />);

    const rate = await screen.findByTitle("24.50 / kg");
    expect(rate.textContent).toContain("₹24.50");
    expect(listPricesMock).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, ordering: "-effective_from" }),
      expect.anything(),
    );
    expect(
      screen.getByText(/entries are never edited or deleted/),
    ).toBeTruthy();
    expect(
      screen.getByText(/keep the price and breakdown they were saved with/),
    ).toBeTruthy();
  });

  it("does not render any edit or delete control", async () => {
    render(<PricesScreen />);
    await screen.findByTitle("24.50 / kg");

    expect(screen.queryByRole("button", { name: /edit/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /edit/i })).toBeNull();
  });

  it("filters by crop/grade, resets the page and clears a stale grade", async () => {
    const user = userEvent.setup();
    render(<PricesScreen />);
    await screen.findByTitle("24.50 / kg");
    await waitForFilters();

    await user.selectOptions(screen.getByLabelText("Filter by crop"), "2");
    await waitFor(() => expect(listPricesMock).toHaveBeenCalledTimes(2));
    expect(lastQuery()).toMatchObject({ page: 1, crop: "2", crop_grade: undefined });

    await user.selectOptions(screen.getByLabelText("Filter by grade"), "11");
    await waitFor(() => expect(listPricesMock).toHaveBeenCalledTimes(3));
    expect(lastQuery()).toMatchObject({ crop: "2", crop_grade: "11" });

    await user.selectOptions(screen.getByLabelText("Filter by crop"), "3");
    await waitFor(() => expect(listPricesMock).toHaveBeenCalledTimes(4));
    expect(lastQuery()).toMatchObject({ crop: "3", crop_grade: undefined });
    expect((screen.getByLabelText("Filter by grade") as HTMLSelectElement).value).toBe("");
  });

  it("explains an empty history", async () => {
    listPricesMock.mockResolvedValue(page([]));
    render(<PricesScreen />);

    expect(await screen.findByText(/No price entries yet/)).toBeTruthy();
  });

  it("refreshes after a successful addition while preserving the active filter", async () => {
    const user = userEvent.setup();
    const added = entry({ id: 6, price_per_kg: "25.00", effective_from: "2027-01-01" });
    createPriceEntryMock.mockResolvedValue(added);
    render(<PricesScreen />);
    await screen.findByTitle("24.50 / kg");
    await waitForFilters();

    await user.selectOptions(screen.getByLabelText("Filter by crop"), "2");
    await waitFor(() => expect(listPricesMock).toHaveBeenCalledTimes(2));

    await user.selectOptions(screen.getByLabelText("Crop"), "2");
    await user.selectOptions(screen.getByLabelText("Grade"), "10");
    await user.type(screen.getByLabelText("Rate (₹/kg)"), "25.00");
    await user.click(screen.getByRole("button", { name: "Add price" }));

    expect(await screen.findByText(/Show this entry in history/)).toBeTruthy();
    await waitFor(() => expect(listPricesMock).toHaveBeenCalledTimes(3));
    expect(lastQuery()).toMatchObject({ page: 1, crop: "2" });
  });

  it("surfaces a network error while loading history", async () => {
    listPricesMock.mockRejectedValue(
      new ApiError({ status: 0, code: "network_error", message: "Network request failed." }),
    );
    render(<PricesScreen />);

    expect(await screen.findByText(/network_error/)).toBeTruthy();
  });
});
