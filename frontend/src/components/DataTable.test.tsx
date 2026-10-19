// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DataTable } from "./DataTable";

afterEach(cleanup);

describe("DataTable", () => {
  it("wraps the table in a labelled, keyboard-focusable scroll region", () => {
    render(
      <DataTable label="Recent deliveries">
        <thead>
          <tr>
            <th>Amount</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>₹245.00</td>
          </tr>
        </tbody>
      </DataTable>,
    );

    const region = screen.getByRole("region", { name: "Recent deliveries" });
    expect(region.getAttribute("tabindex")).toBe("0");
    expect(region.classList.contains("table-wrap")).toBe(true);
    expect(region.querySelector("table.data-table")).toBeTruthy();
    expect(region.textContent).toContain("₹245.00");
  });
});
