// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StatusBadge } from "./StatusBadge";

afterEach(cleanup);

describe("StatusBadge", () => {
  it("always carries a text label plus the tone class", () => {
    render(<StatusBadge tone="finalised">Finalised</StatusBadge>);
    const badge = screen.getByText("Finalised");
    expect(badge.className).toContain("badge");
    expect(badge.className).toContain("badge-finalised");
  });

  it("does not rely on colour alone for a debit note", () => {
    render(<StatusBadge tone="debit">Debit note</StatusBadge>);
    expect(screen.getByText("Debit note")).toBeTruthy();
  });
});
