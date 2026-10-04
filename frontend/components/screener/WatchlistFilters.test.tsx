// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WatchlistFilters } from "@/components/screener/WatchlistFilters";
import type { WatchlistOut } from "@/lib/api/types";

afterEach(cleanup);

const LISTS = [
  { id: 1, name: "E1" },
  { id: 2, name: "ETF" },
  { id: 3, name: "Growth" },
] as unknown as WatchlistOut[];

const options = () => Array.from((screen.getByLabelText(/^Limit results to/) as HTMLSelectElement).options).map((o) => o.textContent);

describe("WatchlistFilters", () => {
  it("leaves the ETF-only list out of the options", () => {
    render(<WatchlistFilters watchlists={LISTS} value={null} onChange={vi.fn()} disabled={false} />);
    expect(options()).toEqual(["None", "E1", "Growth"]);
  });
});
