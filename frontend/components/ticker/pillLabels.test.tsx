// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FairValuePill } from "@/components/ticker/FairValuePill";
import { MoatPill } from "@/components/ticker/MoatPill";
import { PerfVsSpyPill } from "@/components/ticker/PerfVsSpyPill";
import { WeinsteinStagePill } from "@/components/ticker/WeinsteinStagePill";
import { ScoreBadge } from "@/components/step1/ScoreBadge";

afterEach(cleanup);

// Every pill label is sentence case at display time; the source strings
// (MOAT_LABELS, the backend's "Strong Pass") are unchanged.
describe("pill label casing", () => {
  it("re-cases moat labels", () => {
    render(<MoatPill moat="wide_moat" />);
    expect(screen.getByText("Wide moat")).toBeInTheDocument();
  });

  it("re-cases a backend verdict without touching the tone", () => {
    render(<ScoreBadge score={95} verdict="Strong Pass" />);
    const pill = screen.getByText("Strong pass");
    expect(pill.className).toContain("bg-positive-strong/16");
  });

  it("leaves acronyms and single-word labels alone", () => {
    render(
      <>
        <PerfVsSpyPill status="outperform" />
        <FairValuePill verdict="fair" price={100} />
      </>,
    );
    expect(screen.getByText("5Y vs SPY")).toBeInTheDocument();
    expect(screen.getByText(/Fairvalued/)).toBeInTheDocument();
  });

  it("keeps the Stage number/name compound intact", () => {
    render(
      <WeinsteinStagePill
        data={{
          weinstein_stage: "advance",
          weinstein_stage_since_date: null,
          weinstein_stage_since_is_lower_bound: null,
          weinstein_ma_slope_pct: null,
          weinstein_vs_ma_pct: null,
        }}
      />,
    );
    expect(screen.getByText("Stage 2 · Advance")).toBeInTheDocument();
  });
});
