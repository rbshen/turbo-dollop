// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PageHeader } from "@/components/ui/page-header";

afterEach(cleanup);

describe("PageHeader", () => {
  it("renders exactly one h1, the subtitle and the actions", () => {
    render(
      <PageHeader
        title="Screener"
        subtitle="584 of 584 tickers"
        actions={<button type="button">Recompute</button>}
      />,
    );
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Screener");
    expect(screen.getByText("584 of 584 tickers")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recompute" })).toBeInTheDocument();
  });

  it("omits the subtitle and actions blocks when not given", () => {
    render(<PageHeader title="Watchlist" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Watchlist");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
