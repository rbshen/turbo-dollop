// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Badge } from "@/components/ui/badge";

afterEach(cleanup);

describe("Badge", () => {
  it("renders the em dash and ignores children when missing", () => {
    render(<Badge missing>Pass</Badge>);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("Pass")).not.toBeInTheDocument();
  });

  it("renders its label for a normal tone", () => {
    render(<Badge tone="positive">Pass</Badge>);
    expect(screen.getByText("Pass")).toBeInTheDocument();
  });
});
