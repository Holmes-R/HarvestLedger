// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button } from "./Button";
import { Loading, Modal } from "./Modal";

afterEach(cleanup);

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      {open ? (
        <Modal title="Confirm thing" onClose={() => setOpen(false)}>
          Body
        </Modal>
      ) : null}
    </>
  );
}

describe("Modal", () => {
  it("is an accessible dialog labelled by its title", () => {
    render(
      <Modal title="New farmer" onClose={() => undefined}>
        <p>body</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const labelledBy = dialog.getAttribute("aria-labelledby") ?? "";
    expect(document.getElementById(labelledBy)?.textContent).toBe("New farmer");
  });

  it("renders a description and wires it as the accessible description", () => {
    render(
      <Modal title="Confirm" description="This cannot be undone." onClose={() => undefined}>
        <p>body</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");
    const describedBy = dialog.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(describedBy)?.textContent).toBe("This cannot be undone.");
  });

  it("moves focus into the dialog on open", () => {
    render(
      <Modal title="T" onClose={() => undefined}>
        <Button>Inner</Button>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("closes on Escape and restores focus to the trigger", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open dialog" });
    await userEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("calls onClose on a backdrop click only", () => {
    const onClose = vi.fn();
    render(
      <Modal title="T" onClose={onClose}>
        <p>body</p>
      </Modal>,
    );
    fireEvent.mouseDown(screen.getByText("body"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(document.querySelector(".modal-backdrop") as Element);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("traps Tab within the dialog (wraps last → first and first → last)", () => {
    render(
      <Modal
        title="T"
        onClose={() => undefined}
        footer={
          <>
            <Button variant="ghost">Cancel</Button>
            <Button>Confirm</Button>
          </>
        }
      >
        <p>body</p>
      </Modal>,
    );
    const close = screen.getByRole("button", { name: "Close" });
    const confirm = screen.getByRole("button", { name: "Confirm" });

    close.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirm);

    confirm.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(close);
  });
});

describe("Loading", () => {
  it("is a polite live region with a spinner", () => {
    render(<Loading label="Loading payout…" />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Loading payout…");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.querySelector(".spinner")).toBeTruthy();
  });
});
