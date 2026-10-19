import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return { ...actual, collectPages: vi.fn() };
});

import { collectPages } from "./client";
import {
  invalidateFarmerMap,
  invalidateGradeMap,
  loadFarmerMap,
  loadGradeMap,
} from "./lookups";
import type { CropGrade, Farmer } from "./types";

const collectPagesMock = vi.mocked(
  collectPages as unknown as (...args: unknown[]) => Promise<unknown[]>,
);

function farmer(id: number, name: string): Farmer {
  return {
    id,
    name,
    phone: `98765432${String(id).padStart(2, "0")}`,
    village: "Kot",
    bank_reference: "",
    outstanding_advance: "0.00",
    created_at: "2026-05-01T10:00:00+05:30",
  };
}

function grade(id: number): CropGrade {
  return {
    id,
    crop: 2,
    crop_name: "Paddy",
    code: `G${id}`,
    created_at: "2026-05-01T10:00:00+05:30",
  };
}

beforeEach(() => {
  collectPagesMock.mockReset();
  invalidateFarmerMap();
  invalidateGradeMap();
});

describe("reference lookups", () => {
  it("loads farmers from every page, not just the first", async () => {
    collectPagesMock.mockResolvedValueOnce([farmer(1, "First"), farmer(2, "Second")]);

    const map = await loadFarmerMap();

    expect(map.size).toBe(2);
    expect(map.get(2)?.name).toBe("Second");
    expect(collectPagesMock).toHaveBeenCalledWith(
      "/farmers/",
      expect.objectContaining({
        query: { page_size: 100, ordering: "id" },
      }),
    );
  });

  it("loads grades from every page with the same query", async () => {
    collectPagesMock.mockResolvedValueOnce([grade(10), grade(11), grade(12)]);

    const map = await loadGradeMap();

    expect([...map.keys()]).toEqual([10, 11, 12]);
    expect(collectPagesMock).toHaveBeenCalledWith(
      "/grades/",
      expect.objectContaining({
        query: { page_size: 100, ordering: "id" },
      }),
    );
  });

  it("caches until invalidated", async () => {
    collectPagesMock.mockResolvedValue([farmer(1, "First")]);

    await loadFarmerMap();
    await loadFarmerMap();
    expect(collectPagesMock).toHaveBeenCalledTimes(1);

    invalidateFarmerMap();
    await loadFarmerMap();
    expect(collectPagesMock).toHaveBeenCalledTimes(2);
  });
});
