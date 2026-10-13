// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AdminOnly } from "@/components/auth/AdminOnly";
import { TestAuth } from "@/lib/auth/testAuth";

afterEach(cleanup);

const draw = (role: "admin" | "viewer" | null, loading = false, fallback?: string) =>
  render(
    <TestAuth role={role} loading={loading}>
      <AdminOnly fallback={fallback}>
        <button>Delete</button>
      </AdminOnly>
    </TestAuth>,
  );

describe("AdminOnly", () => {
  it("renders its children for an admin", () => {
    draw("admin");
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("renders nothing for a viewer, not a disabled control", () => {
    const { container } = draw("viewer");
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a signed-out visitor", () => {
    const { container } = draw(null);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while the role is still being fetched, so a viewer never sees the control flash", () => {
    const { container } = draw(null, true);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the fallback to a viewer", () => {
    draw("viewer", false, "read-only value");
    expect(screen.getByText("read-only value")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});
