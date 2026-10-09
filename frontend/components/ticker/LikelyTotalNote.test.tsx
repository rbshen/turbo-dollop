// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LikelyTotalNote } from "@/components/ticker/LikelyTotalNote";

afterEach(cleanup);

describe("LikelyTotalNote", () => {
  it("renders nothing without flags", () => {
    const { container } = render(<LikelyTotalNote items={[]} noun="bars" />);
    expect(container).toBeEmptyDOMElement();
    const { container: undef } = render(<LikelyTotalNote items={undefined} noun="bars" />);
    expect(undef).toBeEmptyDOMElement();
  });

  it("shows one amber line per flagged segment", () => {
    render(
      <LikelyTotalNote
        items={[
          { segment: "Revenue Net", years: ["2022", "2023"] },
          { segment: "International Regions", years: ["2025"] },
        ]}
        noun="bars"
      />
    );
    const first = screen.getByText("Revenue Net looks like a total in FY2022-2023, so those bars may be overstated.");
    expect(first).toHaveClass("text-warn");
    expect(screen.getByText(/International Regions looks like a total in FY2025, so that bar may be overstated/)).toBeInTheDocument();
  });
});
