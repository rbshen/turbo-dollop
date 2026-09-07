// Which of Bullish Reversal / Pullback Recovery renders in full vs. collapsed
// on the Technical tab -- each only ever makes sense for one trend direction
// (Bullish Reversal is a downtrend-only read; Pullback Recovery only exists
// once an uptrend has something to pull back from), so exactly one shows in
// full at a time, per the Technical tab redesign's scope-based display rule.
export interface TechnicalCardScope {
  fullCard: "reversal" | "continuation";
  collapsedLabel: string;
  collapsedSubline: string;
}

export function technicalCardScope(trendState: "uptrend" | "downtrend"): TechnicalCardScope {
  if (trendState === "downtrend") {
    return {
      fullCard: "reversal",
      collapsedLabel: "Pullback recovery",
      collapsedSubline: "Only applies during an uptrend — this stock is currently in a downtrend.",
    };
  }
  return {
    fullCard: "continuation",
    collapsedLabel: "Bullish reversal",
    collapsedSubline: "Only applies during a downtrend — this stock is currently in an uptrend.",
  };
}
