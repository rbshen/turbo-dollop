// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StyleguidePage from "@/app/styleguide/page";
import { TestAuth } from "@/lib/auth/testAuth";

const h = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: h.replace }) }));
vi.mock("@/app/styleguide/StyleguideContent", () => ({ StyleguideContent: () => <p>styleguide content</p> }));

afterEach(cleanup);
beforeEach(() => h.replace.mockReset());

describe("/styleguide is admin only", () => {
  it("shows the page to an admin", () => {
    render(
      <TestAuth role="admin">
        <StyleguidePage />
      </TestAuth>,
    );
    expect(screen.getByText("styleguide content")).toBeInTheDocument();
    expect(h.replace).not.toHaveBeenCalled();
  });

  it("sends a viewer home and never mounts the page", () => {
    render(
      <TestAuth role="viewer">
        <StyleguidePage />
      </TestAuth>,
    );
    expect(screen.queryByText("styleguide content")).toBeNull();
    expect(h.replace).toHaveBeenCalledWith("/");
  });

  it("sends a signed-out visitor home too", () => {
    render(
      <TestAuth role={null}>
        <StyleguidePage />
      </TestAuth>,
    );
    expect(h.replace).toHaveBeenCalledWith("/");
  });

  it("waits for the role before deciding", () => {
    render(
      <TestAuth role={null} loading>
        <StyleguidePage />
      </TestAuth>,
    );
    expect(screen.queryByText("styleguide content")).toBeNull();
    expect(h.replace).not.toHaveBeenCalled();
  });
});
