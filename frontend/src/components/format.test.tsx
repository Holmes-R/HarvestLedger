// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DateOnly, Money, Quantity, Timestamp } from "./format";

afterEach(cleanup);

describe("Money", () => {
  it("renders a grouped rupee value without losing decimals", () => {
    render(<Money value="123456.78" />);
    expect(screen.getByText("\u20B91,23,456.78")).toBeTruthy();
  });

  it("keeps trailing zeros intact", () => {
    render(<Money value="245.00" />);
    expect(screen.getByText("\u20B9245.00")).toBeTruthy();
  });

  it("renders an em dash with no currency sign for missing values", () => {
    const { container } = render(<Money value={null} />);
    expect(container.textContent).toBe("\u2014");
  });

  it("appends a suffix for per-unit prices", () => {
    render(<Money value="24.50" suffix=" / kg" />);
    expect(screen.getByText("/ kg")).toBeTruthy();
  });
});

describe("DateOnly", () => {
  it("formats a date-only value and never shifts the day", () => {
    const { container } = render(<DateOnly value="2026-05-01" />);
    expect(container.textContent).toBe("01 May 2026");
    expect(container.querySelector("time")?.getAttribute("datetime")).toBe("2026-05-01");
  });

  it("falls back for a missing date", () => {
    const { container } = render(<DateOnly value={null} />);
    expect(container.textContent).toBe("\u2014");
  });
});

describe("Timestamp", () => {
  it("renders an audit timestamp explicitly in Asia/Kolkata (IST)", () => {
    // 09:00 UTC is 14:30 in Asia/Kolkata.
    const { container } = render(<Timestamp value="2026-10-19T09:00:00Z" />);
    expect(container.textContent).toContain("19 Oct 2026");
    expect(container.textContent).toContain("14:30");
    expect(container.textContent).toMatch(/IST$/);
  });

  it("exposes the raw value and zone in the tooltip", () => {
    render(<Timestamp value="2026-10-19T09:00:00Z" />);
    const el = screen.getByText(/IST$/);
    expect(el.getAttribute("title")).toContain("Asia/Kolkata");
    expect(el.getAttribute("datetime")).toBe("2026-10-19T09:00:00Z");
  });
});

describe("Quantity", () => {
  it("renders a raw decimal with its unit", () => {
    const { container } = render(<Quantity value="100.125" unit="kg" />);
    expect(container.textContent).toBe("100.125 kg");
  });
});
