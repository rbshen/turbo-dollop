// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MetricsGrid } from "@/components/ticker/MetricsGrid";
import type { MetricGroup } from "@/lib/metrics/config";
import type { TickerSummaryOut } from "@/lib/api/types";

afterEach(cleanup);

const GROUPS: MetricGroup[] = [
  {
    title: "Classification",
    column: "left",
    metrics: [{ key: "sector", label: "Sector", format: "text" }],
  },
  {
    title: "Performance",
    column: "right",
    metrics: [{ key: "market_cap", label: "Market Cap", format: "compactMoney" }],
  },
];

const VALUES = { sector: "Technology", market_cap: 3_000_000_000, quote_currency: "USD" } as unknown as TickerSummaryOut;

describe("MetricsGrid", () => {
  it("renders each group as a titled section with its metrics, no boxed card wrapper", () => {
    const { container } = render(<MetricsGrid groups={GROUPS} values={VALUES} />);
    expect(screen.getByText("Classification")).toBeInTheDocument();
    expect(screen.getByText("Performance")).toBeInTheDocument();
    expect(screen.getByText("Sector")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("Market Cap")).toBeInTheDocument();
    expect(container.querySelector(".rounded-lg.border-border-card")).toBeNull();
    expect(container.querySelector(".bg-surface")).toBeNull();
  });
});

describe("MetricsGrid enterprise value currency", () => {
  const EV_GROUPS: MetricGroup[] = [
    {
      title: "Size & Valuation",
      column: "left",
      metrics: [
        { key: "market_cap", label: "Market Cap", format: "compactMoney" },
        { key: "enterprise_value", label: "Enterprise Value", format: "compactMoney", currency: "reported" },
      ],
    },
  ];

  function values(overrides: Partial<TickerSummaryOut>): TickerSummaryOut {
    return { market_cap: 2_349_000_000_000, enterprise_value: 76_710_000_000_000, quote_currency: "USD", reported_currency: "USD", ...overrides } as unknown as TickerSummaryOut;
  }

  it("shows a USD reporter's EV exactly as before -- $ prefix, no currency suffix", () => {
    render(<MetricsGrid groups={EV_GROUPS} values={values({ enterprise_value: 2_300_000_000_000 })} />);
    expect(screen.getByText("$2.30T")).toBeInTheDocument();
    expect(screen.queryByTitle(/not converted/)).toBeNull();
  });

  it("shows a non-USD reporter's EV in the reported currency (TWD fallback prefix), market cap still in USD", () => {
    render(<MetricsGrid groups={EV_GROUPS} values={values({ reported_currency: "TWD" })} />);
    expect(screen.getByText("$2.35T")).toBeInTheDocument();
    expect(screen.getByText("TWD 76.71T")).toBeInTheDocument();
    expect(screen.queryByText("$76.71T")).toBeNull();
    // the prefix already names the currency, so no redundant ISO-code badge
    expect(screen.queryByTitle(/not converted/)).toBeNull();
  });

  it("appends the ISO code when the reported currency has a symbol prefix (CNY -> CN¥)", () => {
    render(<MetricsGrid groups={EV_GROUPS} values={values({ reported_currency: "CNY", enterprise_value: 1_601_000_000_000 })} />);
    expect(screen.getByText("CN¥1.60T")).toBeInTheDocument();
    expect(screen.getByTitle("Reported in CNY, not converted to USD")).toHaveTextContent("CNY");
  });

  it("falls back to the quote currency when reported_currency is null", () => {
    render(<MetricsGrid groups={EV_GROUPS} values={values({ reported_currency: null, enterprise_value: 5_000_000_000 })} />);
    expect(screen.getByText("$5.00B")).toBeInTheDocument();
  });

  it("renders no currency badge when EV is missing", () => {
    render(<MetricsGrid groups={EV_GROUPS} values={values({ reported_currency: "CNY", enterprise_value: null })} />);
    expect(screen.queryByTitle(/not converted/)).toBeNull();
  });
});
