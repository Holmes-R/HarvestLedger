// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button } from "./Button";

afterEach(cleanup);

describe("Button", () => {
  it("renders as an accessible button with its label", () => {
    render(<Button>Record delivery</Button>);
    expect(screen.getByRole("button", { name: "Record delivery" })).toBeTruthy();
  });

  it("exposes a pending-action control: disabled, aria-busy and a pending label", () => {
    render(
      <Button pending pendingLabel="Recording…">
        Record delivery
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Recording…" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.querySelector(".spinner")).toBeTruthy();
  });

  it("does not raise a click while pending", async () => {
    const onClick = vi.fn();
    render(
      <Button pending pendingLabel="Saving…" onClick={onClick}>
        Save
      </Button>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Saving…" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("maps variants to the shared classes", () => {
    render(
      <>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Danger</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Ghost" }).className).toContain("button-ghost");
    expect(screen.getByRole("button", { name: "Danger" }).className).toContain("button-danger");
  });
});
