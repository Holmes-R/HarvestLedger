import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import type { CropGrade } from "../api/types";
import {
  classifyEffectiveDate,
  cropOptionsFromGrades,
  effectiveDateNote,
  gradeOptionsFromGrades,
  priceConflict,
  PRICE_ORDERING,
  validatePriceEntry,
} from "./pricing";

const valid = {
  cropId: "2",
  gradeId: "10",
  price: "24.50",
  effectiveFrom: "2026-05-01",
};

const grade = (id: number, crop: number, cropName: string, code: string): CropGrade => ({
  id,
  crop,
  crop_name: cropName,
  code,
  created_at: "2026-05-01T10:00:00+05:30",
});

describe("validatePriceEntry", () => {
  it("accepts a complete, well-formed entry", () => {
    expect(validatePriceEntry(valid)).toEqual({
      crop: null,
      grade: null,
      price: null,
      date: null,
      valid: true,
    });
  });

  it("requires crop, grade, rate and date", () => {
    const result = validatePriceEntry({
      cropId: "",
      gradeId: "",
      price: "",
      effectiveFrom: "",
    });
    expect(result.valid).toBe(false);
    expect(result.crop).toBe("Select a crop.");
    expect(result.grade).toBe("Select a grade.");
    expect(result.price).toBe("Required.");
    expect(result.date).toBe("Select an effective date.");
  });

  it("rejects excess precision and non-positive rates", () => {
    const precise = validatePriceEntry({ ...valid, price: "24.555" });
    expect(precise.valid).toBe(false);
    expect(precise.price).toMatch(/2 decimal places/);

    const zero = validatePriceEntry({ ...valid, price: "0" });
    expect(zero.valid).toBe(false);
    expect(zero.price).toMatch(/greater than zero/);
  });

  it("rejects impossible and malformed dates", () => {
    expect(validatePriceEntry({ ...valid, effectiveFrom: "2026-02-30" }).date).toBe(
      "Enter a valid date (YYYY-MM-DD).",
    );
    expect(validatePriceEntry({ ...valid, effectiveFrom: "01-05-2026" }).date).toBe(
      "Enter a valid date (YYYY-MM-DD).",
    );
  });
});

describe("classifyEffectiveDate / effectiveDateNote", () => {
  const today = "2026-05-01";

  it("classifies past, current and future dates", () => {
    expect(classifyEffectiveDate("2026-04-30", today)).toBe("past");
    expect(classifyEffectiveDate("2026-05-01", today)).toBe("today");
    expect(classifyEffectiveDate("2026-05-02", today)).toBe("future");
  });

  it("explains that history is never overwritten or retro-applied", () => {
    expect(effectiveDateNote("past")).toMatch(/never overwrites/);
    expect(effectiveDateNote("past")).toMatch(/keep the price/);
    expect(effectiveDateNote("future")).toMatch(/on or after this date/);
    expect(effectiveDateNote("today")).toMatch(/on or after today/);
  });
});

describe("priceConflict", () => {
  it("maps a duplicate effective date to the date field with append-only advice", () => {
    const conflict = priceConflict(
      new ApiError({ status: 409, code: "price_already_exists", message: "duplicate" }),
    );
    expect(conflict?.field).toBe("date");
    expect(conflict?.message).toMatch(/append-only/);
    expect(conflict?.message).toMatch(/choose a different date/);
  });

  it("maps an unallowed grade to the grade field", () => {
    expect(
      priceConflict(
        new ApiError({ status: 422, code: "grade_not_allowed", message: "no" }),
      )?.field,
    ).toBe("grade");
  });

  it("ignores unrelated errors", () => {
    expect(
      priceConflict(new ApiError({ status: 0, code: "network_error", message: "x" })),
    ).toBeNull();
  });
});

describe("option helpers", () => {
  const grades = new Map([
    [10, grade(10, 2, "Paddy", "A")],
    [11, grade(11, 2, "Paddy", "B")],
    [12, grade(12, 3, "Maize", "A")],
  ]);

  it("dedupes crops and sorts by name", () => {
    expect(cropOptionsFromGrades(grades)).toEqual([
      { value: "3", label: "Maize" },
      { value: "2", label: "Paddy" },
    ]);
  });

  it("filters grades by crop and labels them with the crop when unfiltered", () => {
    expect(gradeOptionsFromGrades(grades, "2")).toEqual([
      { value: "10", label: "A" },
      { value: "11", label: "B" },
    ]);
    expect(gradeOptionsFromGrades(grades, "")).toContainEqual({
      value: "12",
      label: "Maize · A",
    });
  });
});

describe("PRICE_ORDERING", () => {
  it("requests the newest effective date first (stable id tie-breaker server-side)", () => {
    expect(PRICE_ORDERING).toBe("-effective_from");
  });
});
