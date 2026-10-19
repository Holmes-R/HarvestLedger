// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { ErrorBanner } from "./ErrorBanner";

afterEach(cleanup);

function error(overrides: Partial<ConstructorParameters<typeof ApiError>[0]> = {}) {
  return new ApiError({
    status: 400,
    code: "invalid",
    message: "Invalid input.",
    details: { gross_weight_kg: [{ code: "invalid", message: "Enter a number." }] },
    requestId: "req-12345678",
    method: "POST",
    path: "/deliveries/",
    isWrite: true,
    outcome: "rejected",
    ...overrides,
  });
}

describe("ErrorBanner", () => {
  it("renders nothing without an error", () => {
    const { container } = render(<ErrorBanner error={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it("announces the error in text (not colour alone) with code and request id", () => {
    render(<ErrorBanner error={error()} />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Error");
    expect(alert.textContent).toContain("invalid");
    expect(alert.textContent).toContain("HTTP 400");
    expect(alert.textContent).toContain("gross_weight_kg: Enter a number.");
    expect(alert.textContent).toContain("req-12345678");
  });

  it("surfaces the unknown-write warning only for an in-doubt write", () => {
    const { rerender } = render(<ErrorBanner error={error()} />);
    expect(screen.queryByText(/may or may not have been applied/)).toBeNull();

    rerender(
      <ErrorBanner
        error={error({ status: 0, code: "network_error", outcome: "unknown" })}
      />,
    );
    expect(screen.getByText(/may or may not have been applied/)).toBeTruthy();
  });
});
