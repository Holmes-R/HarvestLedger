import { describe, expect, it } from "vitest";

import { compareDecimal, decimalPlaces, formatAmount, formatMoney, isDecimal, validateDecimal } from "./decimal";

describe("formatAmount", () => {
  it("groups the integer part in the Indian style", () => {
    expect(formatAmount("1234567")).toBe("12,34,567");
    expect(formatAmount("12345")).toBe("12,345");
    expect(formatAmount("1234")).toBe("1,234");
    expect(formatAmount("123")).toBe("123");
  });

  it("keeps the fractional part verbatim, including trailing zeros", () => {
    expect(formatAmount("245.00")).toBe("245.00");
    expect(formatAmount("12345.67890")).toBe("12,345.67890");
  });

  it("handles a leading minus sign", () => {
    expect(formatAmount("-1234.5")).toBe("-1,234.5");
  });

  it("falls back to an em dash for empty input", () => {
    expect(formatAmount(null)).toBe("\u2014");
    expect(formatAmount(undefined)).toBe("\u2014");
    expect(formatAmount("")).toBe("\u2014");
  });

  it("returns unparseable input unchanged rather than mangling it", () => {
    expect(formatAmount("not-a-number")).toBe("not-a-number");
  });
});

describe("formatMoney", () => {
  it("prefixes the rupee sign and preserves precision", () => {
    expect(formatMoney("245.00")).toBe("\u20B9245.00");
    expect(formatMoney("123456.78")).toBe("\u20B91,23,456.78");
  });

  it("keeps the em dash without a currency sign", () => {
    expect(formatMoney(null)).toBe("\u2014");
  });
});

describe("decimal helpers", () => {
  it("counts and validates decimal places", () => {
    expect(decimalPlaces("1.23")).toBe(2);
    expect(decimalPlaces("10")).toBe(0);
    expect(isDecimal("1.23")).toBe(true);
    expect(isDecimal("1,23")).toBe(false);
    expect(validateDecimal("24.50", { places: 2, positive: true })).toBeNull();
    expect(validateDecimal("24.567", { places: 2 })).toBe("At most 2 decimal places.");
    expect(validateDecimal("0", { places: 2, positive: true })).toBe("Must be greater than zero.");
    expect(validateDecimal("", { places: 2 })).toBe("Required.");
  });

  it("compares decimal strings without parsing them as floats", () => {
    expect(compareDecimal("0", "0.00")).toBe(0);
    expect(compareDecimal("-1", "0")).toBe(-1);
    expect(compareDecimal("100", "100.01")).toBe(-1);
    expect(compareDecimal("14.5", "14.50")).toBe(0);
    expect(compareDecimal("0014.05", "14.5")).toBe(-1);
    expect(compareDecimal("not-a-number", "1")).toBeNull();
  });
});
