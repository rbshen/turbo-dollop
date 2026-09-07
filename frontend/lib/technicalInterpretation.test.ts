import { describe, expect, it } from "vitest";

import { buildInterpretation, type InterpretationInputs } from "@/lib/technicalInterpretation";

function inputs(overrides: Partial<InterpretationInputs>): InterpretationInputs {
  return {
    weinsteinStage: "advance",
    trendState: "uptrend",
    regime: "trending",
    reversalStatus: "Not present",
    continuationStatus: "NoPullback",
    ...overrides,
  };
}

describe("buildInterpretation -- Layer 1 (stage frame)", () => {
  it("Stage 2 (Advance) sets a solid-long-term-uptrend frame", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "advance" }));
    expect(lead.startsWith("This stock has been on a solid long-term uptrend")).toBe(true);
  });

  it("Stage 1 (Base) sets a not-going-anywhere frame", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "base" }));
    expect(lead.startsWith("This stock isn't really going anywhere long-term yet — just settling")).toBe(true);
  });

  it("Stage 3 (Top) sets a running-out-of-steam frame", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "top" }));
    expect(lead.startsWith("This stock's long-term uptrend may be running out of steam")).toBe(true);
  });

  it("Stage 4 (Decline) sets a long-term-downtrend frame", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "decline" }));
    expect(lead.startsWith("This stock has been on a long-term downtrend")).toBe(true);
  });

  it("omits Layer 1 entirely when the stage is null, starting from Layer 2 as its own sentence", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: null, trendState: "uptrend", regime: "trending" }));
    expect(lead).toBe("It's currently climbing steadily.");
    expect(lead.startsWith("This stock")).toBe(false);
  });
});

describe("buildInterpretation -- Layer 2 (trend/regime texture)", () => {
  it("Advance + Uptrend + Trending reads as reinforcing the long-term uptrend", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "advance", trendState: "uptrend", regime: "trending" }));
    expect(lead).toBe("This stock has been on a solid long-term uptrend and it's still climbing steadily right now.");
  });

  it("Advance + Uptrend + Range-bound reads as a pause, not a reversal", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "advance", trendState: "uptrend", regime: "range-bound" }));
    expect(lead).toBe(
      "This stock has been on a solid long-term uptrend though it's lost some steam lately, moving sideways more than up."
    );
  });

  it("Advance + Downtrend + Range-bound reads as a rough patch, not a real breakdown", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "advance", trendState: "downtrend", regime: "range-bound" }));
    expect(lead).toBe(
      "This stock has been on a solid long-term uptrend but it's in a rough patch right now — drifting down without much conviction, not a real breakdown."
    );
  });

  it("Advance + Downtrend + Trending reads as a real, sharp break", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "advance", trendState: "downtrend", regime: "trending" }));
    expect(lead).toBe("This stock has been on a solid long-term uptrend but it's fallen sharply lately — worth keeping an eye on.");
  });

  it("Stage-4 flip: an uptrend reading during a Decline stage reads as a bounce, never a real turnaround", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "decline", trendState: "uptrend", regime: "trending" }));
    expect(lead).toBe("This stock has been on a long-term downtrend though it's seeing a short-term bounce right now.");
    expect(lead).not.toMatch(/climbing steadily/);
  });

  it("Decline + Uptrend + Range-bound reads as a tentative stabilization, not a recovery", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "decline", trendState: "uptrend", regime: "range-bound" }));
    expect(lead).toBe("This stock has been on a long-term downtrend though it's attempting to stabilize, drifting sideways for now.");
  });

  it("Decline + Downtrend + Range-bound reinforces the decline without implying a fresh breakdown", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "decline", trendState: "downtrend", regime: "range-bound" }));
    expect(lead).toBe("This stock has been on a long-term downtrend and that decline continues, albeit without much conviction right now.");
  });

  it("Decline + Downtrend + Trending reinforces the decline as firmly in force", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "decline", trendState: "downtrend", regime: "trending" }));
    expect(lead).toBe(
      "This stock has been on a long-term downtrend and it's continuing to fall sharply — the downtrend remains firmly in force."
    );
  });

  it("Base + Uptrend + Trending reads as momentum within the range, not an established trend", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "base", trendState: "uptrend", regime: "trending" }));
    expect(lead).toBe(
      "This stock isn't really going anywhere long-term yet — just settling though it's showing some real short-term upward momentum within that range."
    );
  });

  it("Base + Uptrend + Range-bound reads as mild drift within the range", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "base", trendState: "uptrend", regime: "range-bound" }));
    expect(lead).toBe(
      "This stock isn't really going anywhere long-term yet — just settling and for now it's drifting slightly higher within that range."
    );
  });

  it("Base + Downtrend + Range-bound reads as mild drift within the range", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "base", trendState: "downtrend", regime: "range-bound" }));
    expect(lead).toBe(
      "This stock isn't really going anywhere long-term yet — just settling and for now it's drifting slightly lower within that range."
    );
  });

  it("Base + Downtrend + Trending flags a real pullback that could break the base", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "base", trendState: "downtrend", regime: "trending" }));
    expect(lead).toBe(
      "This stock isn't really going anywhere long-term yet — just settling though it's pulling back hard within that range right now — worth watching in case it breaks down for real."
    );
  });

  it("Top + Uptrend + Trending still reads as climbing, cautiously, given the topping frame", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "top", trendState: "uptrend", regime: "trending" }));
    expect(lead).toBe("This stock's long-term uptrend may be running out of steam though it's still climbing for now.");
  });

  it("Top + Uptrend + Range-bound reads as stalling, the expected topping texture", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "top", trendState: "uptrend", regime: "range-bound" }));
    expect(lead).toBe(
      "This stock's long-term uptrend may be running out of steam and it's stalling out, moving sideways rather than higher."
    );
  });

  it("Top + Downtrend + Range-bound reads as an early slip, not yet a clear break", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "top", trendState: "downtrend", regime: "range-bound" }));
    expect(lead).toBe(
      "This stock's long-term uptrend may be running out of steam and it's starting to slip, drifting lower without a clear break yet."
    );
  });

  it("Top + Downtrend + Trending reads as the topping thesis playing out in earnest", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "top", trendState: "downtrend", regime: "trending" }));
    expect(lead).toBe(
      "This stock's long-term uptrend may be running out of steam and it's now breaking down in earnest — worth watching closely."
    );
  });

  it("falls back to a regime-agnostic clause when regime is null (e.g. too little history)", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: "advance", trendState: "uptrend", regime: null }));
    expect(lead).toBe("This stock has been on a solid long-term uptrend and it's currently climbing.");
  });

  it("null stage + downtrend + range-bound reads as a standalone rough-patch sentence", () => {
    const [lead] = buildInterpretation(inputs({ weinsteinStage: null, trendState: "downtrend", regime: "range-bound" }));
    expect(lead).toBe("It's in a rough patch right now — drifting down without much conviction, not a real breakdown.");
  });
});

describe("buildInterpretation -- Layer 3 (tactical footnote)", () => {
  it("omits the footnote entirely when reversal is Not present and continuation is NoPullback", () => {
    const sentences = buildInterpretation(inputs({ reversalStatus: "Not present", continuationStatus: "NoPullback" }));
    expect(sentences).toHaveLength(1);
  });

  it("adds the Recovered footnote", () => {
    const sentences = buildInterpretation(inputs({ trendState: "uptrend", reversalStatus: "Not present", continuationStatus: "Recovered" }));
    expect(sentences).toEqual([sentences[0], "It recently dipped and already bounced back."]);
  });

  it("adds the Pending footnote", () => {
    const sentences = buildInterpretation(inputs({ trendState: "uptrend", reversalStatus: "Not present", continuationStatus: "Pending" }));
    expect(sentences[1]).toBe("It's dipping right now — too soon to say if it'll bounce back or not.");
  });

  it("adds the Invalidated footnote", () => {
    const sentences = buildInterpretation(inputs({ trendState: "downtrend", reversalStatus: "Not present", continuationStatus: "Invalidated" }));
    expect(sentences[1]).toBe("It tried to dip and recover, but that didn't work out — the slide continued.");
  });

  it("adds the Reversal-Confirmed footnote", () => {
    // Only reachable alongside continuationStatus="Invalidated" in real data
    // (see the next test), but the function itself doesn't enforce that --
    // it just reflects whatever statuses it's given.
    const sentences = buildInterpretation(
      inputs({ trendState: "downtrend", reversalStatus: "Confirmed", continuationStatus: "Invalidated" })
    );
    expect(sentences[1]).toBe("It tried to dip and recover, but that didn't work out — the slide continued.");
    expect(sentences[2]).toBe("There are also early signs it might be bottoming out short-term.");
    expect(sentences).toHaveLength(3);
  });
});
