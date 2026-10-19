// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Field, Select, TextInput } from "./form";

afterEach(cleanup);

describe("Field", () => {
  it("associates the label with the wrapped input", () => {
    render(
      <Field label="Gross weight (kg)">
        <TextInput value="" onChange={() => undefined} />
      </Field>,
    );
    expect(screen.getByLabelText("Gross weight (kg)")).toBeTruthy();
  });

  it("links the input to explicit htmlFor/id and its hint", () => {
    render(
      <Field label="Moisture %" htmlFor="m" hint="Above the threshold, weight is reduced.">
        <TextInput id="m" value="" onChange={() => undefined} />
      </Field>,
    );
    const input = screen.getByLabelText("Moisture %");
    expect(input.id).toBe("m");
    const describedBy = input.getAttribute("aria-describedby") ?? "";
    expect(describedBy).toContain("m-hint");
    expect(input.getAttribute("aria-invalid")).toBeNull();
  });

  it("marks the input invalid and associates the error text (not colour alone)", () => {
    render(
      <Field label="Price (₹/kg)" htmlFor="p" error="At most 2 decimal places.">
        <TextInput id="p" value="24.567" onChange={() => undefined} />
      </Field>,
    );
    const input = screen.getByLabelText("Price (₹/kg)");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toContain("p-error");

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Error:");
    expect(alert.textContent).toContain("At most 2 decimal places.");
  });

  it("works for selects too", () => {
    render(
      <Field label="Grade" htmlFor="g">
        <Select
          id="g"
          value=""
          onChange={() => undefined}
          placeholder="Select…"
          options={[{ value: "1", label: "A" }]}
        />
      </Field>,
    );
    expect(screen.getByLabelText("Grade")).toBeTruthy();
  });

  it("supports an explicit aria-label for standalone controls", () => {
    render(
      <Select
        value=""
        onChange={() => undefined}
        ariaLabel="Filter by crop"
        options={[{ value: "1", label: "Rice" }]}
      />,
    );
    expect(screen.getByLabelText("Filter by crop")).toBeTruthy();
  });
});
