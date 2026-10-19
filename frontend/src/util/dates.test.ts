import { describe, expect, it } from "vitest";

import {
  isApiDate,
  isApiTimestamp,
  istToday,
  mondayOf,
  sundayOf,
  toApiDate,
} from "./dates";

function isoDay(date: string): number {
  return new Date(`${date}T00:00:00Z`).getUTCDay();
}

describe("toApiDate", () => {
  it("passes a bare calendar date through", () => {
    expect(toApiDate("2026-05-01")).toBe("2026-05-01");
  });

  it("reduces an ISO instant to its IST calendar date", () => {
    expect(toApiDate("2026-05-01T06:00:00Z")).toBe("2026-05-01");
    // 20:00 UTC is already the next day in IST.
    expect(toApiDate("2026-05-01T20:00:00Z")).toBe("2026-05-02");
  });

  it("reduces a Date to its IST calendar date", () => {
    expect(toApiDate(new Date("2026-05-01T20:00:00Z"))).toBe("2026-05-02");
  });

  it("throws on input the API could never accept", () => {
    expect(() => toApiDate("not a date")).toThrow();
    expect(() => toApiDate(new Date(Number.NaN))).toThrow();
  });
});

describe("isApiDate", () => {
  it("accepts only YYYY-MM-DD", () => {
    expect(isApiDate("2026-05-01")).toBe(true);
    expect(isApiDate("2026-5-1")).toBe(false);
    expect(isApiDate("2026-05-01T00:00:00Z")).toBe(false);
  });
});

describe("isApiTimestamp", () => {
  it("requires a timezone-aware instant", () => {
    expect(isApiTimestamp("2026-12-31T23:00:00+05:30")).toBe(true);
    expect(isApiTimestamp("2026-12-31T23:00:00Z")).toBe(true);
    expect(isApiTimestamp("2026-12-31T23:00")).toBe(false);
    expect(isApiTimestamp("2026-12-31 23:00:00")).toBe(false);
  });
});

describe("week bounds", () => {
  it("maps any day to Monday..Sunday", () => {
    const monday = mondayOf("2026-05-06");
    const sunday = sundayOf("2026-05-06");
    expect(isoDay(monday)).toBe(1);
    expect(isoDay(sunday)).toBe(0);
  });

  it("istToday is a bare date", () => {
    expect(isApiDate(istToday())).toBe(true);
  });
});
