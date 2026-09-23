// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { IndexMembershipPill } from "@/components/ticker/IndexMembershipPill";

afterEach(cleanup);

describe("IndexMembershipPill", () => {
  it("renders nothing when memberships is empty", () => {
    const { container } = render(<IndexMembershipPill memberships={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when memberships is null/undefined", () => {
    const { container: nullContainer } = render(<IndexMembershipPill memberships={null} />);
    expect(nullContainer).toBeEmptyDOMElement();
    cleanup();
    const { container: undefinedContainer } = render(<IndexMembershipPill memberships={undefined} />);
    expect(undefinedContainer).toBeEmptyDOMElement();
  });

  it("renders a single membership with its label", () => {
    render(<IndexMembershipPill memberships={["sp500"]} />);
    expect(screen.getByText("S&P 500")).toBeInTheDocument();
  });

  it("renders multiple memberships joined in the given order", () => {
    render(<IndexMembershipPill memberships={["sp500", "nasdaq"]} />);
    expect(screen.getByText("S&P 500 · Nasdaq")).toBeInTheDocument();
  });

  it("renders all three memberships in a fixed order", () => {
    render(<IndexMembershipPill memberships={["sp500", "nasdaq", "dow"]} />);
    expect(screen.getByText("S&P 500 · Nasdaq · Dow 30")).toBeInTheDocument();
  });

  it("falls back to the raw name for an unrecognized index", () => {
    render(<IndexMembershipPill memberships={["russell2000"]} />);
    expect(screen.getByText("russell2000")).toBeInTheDocument();
  });
});
