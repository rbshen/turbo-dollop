import type { ResolutionStatus } from "@/components/technical/TrendContinuationCard";
import type { ReversalStatus } from "@/components/technical/ReversalCard";
import type { WeinsteinStage } from "@/lib/weinsteinStage";

export interface InterpretationInputs {
  weinsteinStage: WeinsteinStage | null;
  trendState: "uptrend" | "downtrend";
  regime: "trending" | "range-bound" | null;
  reversalStatus: ReversalStatus;
  continuationStatus: ResolutionStatus;
}

// LAYER 1 -- the long-term frame. Omitted entirely when the stage can't be
// read yet (thin history/never computed) -- see buildInterpretation.
const STAGE_FRAME: Record<WeinsteinStage, string> = {
  advance: "This stock has been on a solid long-term uptrend",
  base: "This stock isn't really going anywhere long-term yet — just settling",
  top: "This stock's long-term uptrend may be running out of steam",
  decline: "This stock has been on a long-term downtrend",
};

type Regime = "trending" | "range-bound";
// "unknown" -- regime itself can be null (e.g. too little history for the
// 60-day efficiency-ratio window) independently of weinstein_stage -- a
// simpler, regime-agnostic clause for that case.
type RegimeKey = Regime | "unknown";

// LAYER 2 -- near-term trend/regime texture, appended to Layer 1 (or, for a
// null stage, standing alone as its own capitalized sentence -- the "none"
// row below). Deliberately keyed by stage: the SAME trend_state/regime
// reading means something different depending on the long-term frame it
// sits inside (e.g. an uptrend reading during a Stage 4 decline is a bounce,
// not a real recovery -- the "Stage-4 flip" case), so the wording adapts
// per stage rather than reusing one fixed template with a swapped
// connector word.
const LAYER2: Record<WeinsteinStage | "none", Record<"uptrend" | "downtrend", Record<RegimeKey, string>>> = {
  advance: {
    uptrend: {
      trending: "and it's still climbing steadily right now.",
      "range-bound": "though it's lost some steam lately, moving sideways more than up.",
      unknown: "and it's currently climbing.",
    },
    downtrend: {
      trending: "but it's fallen sharply lately — worth keeping an eye on.",
      "range-bound": "but it's in a rough patch right now — drifting down without much conviction, not a real breakdown.",
      unknown: "but it's currently pulling back.",
    },
  },
  base: {
    uptrend: {
      trending: "though it's showing some real short-term upward momentum within that range.",
      "range-bound": "and for now it's drifting slightly higher within that range.",
      unknown: "and it's edging higher for now.",
    },
    downtrend: {
      trending: "though it's pulling back hard within that range right now — worth watching in case it breaks down for real.",
      "range-bound": "and for now it's drifting slightly lower within that range.",
      unknown: "and it's edging lower for now.",
    },
  },
  top: {
    uptrend: {
      trending: "though it's still climbing for now.",
      "range-bound": "and it's stalling out, moving sideways rather than higher.",
      unknown: "though it's still pushing higher for now.",
    },
    downtrend: {
      trending: "and it's now breaking down in earnest — worth watching closely.",
      "range-bound": "and it's starting to slip, drifting lower without a clear break yet.",
      unknown: "and it's starting to roll over.",
    },
  },
  decline: {
    // Stage-4 flip: an uptrend reading here is a bounce inside the larger
    // decline, never framed as a real turnaround.
    uptrend: {
      trending: "though it's seeing a short-term bounce right now.",
      "range-bound": "though it's attempting to stabilize, drifting sideways for now.",
      unknown: "though it's attempting a short-term bounce.",
    },
    downtrend: {
      trending: "and it's continuing to fall sharply — the downtrend remains firmly in force.",
      "range-bound": "and that decline continues, albeit without much conviction right now.",
      unknown: "and that decline continues.",
    },
  },
  // Null-stage variants stand alone (no Layer 1 to attach to), so each is
  // already a complete, capitalized sentence rather than a lowercase
  // trailing clause.
  none: {
    uptrend: {
      trending: "It's currently climbing steadily.",
      "range-bound": "It's currently drifting sideways, having lost some steam lately.",
      unknown: "It's currently climbing.",
    },
    downtrend: {
      trending: "It's fallen sharply lately — worth keeping an eye on.",
      "range-bound": "It's in a rough patch right now — drifting down without much conviction, not a real breakdown.",
      unknown: "It's currently pulling back.",
    },
  },
};

function regimeKey(regime: "trending" | "range-bound" | null): RegimeKey {
  return regime ?? "unknown";
}

// LAYER 3 -- tactical footnote(s), appended as additional sentence(s), only
// when there's something worth noting (reversal="Not present" AND
// continuation="NoPullback" contributes nothing, so the array comes back
// empty and the caller adds no second sentence at all).
//
// Reversal="Confirmed" and a Continuation status are NOT mutually exclusive
// -- checked directly against the state machine's own invariants (see
// reversalStatus's own comment in ReversalCard.tsx): reversalStatus can only
// ever read "Confirmed" while trend_state="downtrend", and
// resolutionStatus's very first check unconditionally returns "Invalidated"
// whenever trend_state="downtrend". So reversalStatus="Confirmed" doesn't
// just CAN co-occur with continuationStatus="Invalidated" -- it ALWAYS does,
// every single time it fires (never alongside NoPullback/Pending/Recovered,
// which all require an uptrend). Both notes are pushed independently below,
// continuation first: the invalidation is the "what already happened" fact,
// and the reversal note reads naturally as a following "but here's a new
// sign" addendum, e.g. "...the slide continued. There are also early signs
// it might be bottoming out short-term."
function layer3(reversal: ReversalStatus, continuation: ResolutionStatus): string[] {
  const notes: string[] = [];
  if (continuation === "Recovered") {
    notes.push("It recently dipped and already bounced back.");
  } else if (continuation === "Pending") {
    notes.push("It's dipping right now — too soon to say if it'll bounce back or not.");
  } else if (continuation === "Invalidated") {
    notes.push("It tried to dip and recover, but that didn't work out — the slide continued.");
  }
  if (reversal === "Confirmed") {
    notes.push("There are also early signs it might be bottoming out short-term.");
  }
  return notes;
}

// Pure plain-English summary over five already-computed fields -- no new
// backend computation, no new persisted data. Returns each sentence
// separately (1-3 entries: the Layer 1+2 sentence, plus 0-2 Layer 3
// footnotes) so callers/tests can inspect them individually; join with a
// space to render as running prose.
export function buildInterpretation(inputs: InterpretationInputs): string[] {
  const { weinsteinStage, trendState, regime, reversalStatus: reversal, continuationStatus: continuation } = inputs;
  const rKey = regimeKey(regime);

  const leadSentence = weinsteinStage
    ? `${STAGE_FRAME[weinsteinStage]} ${LAYER2[weinsteinStage][trendState][rKey]}`
    : LAYER2.none[trendState][rKey];

  return [leadSentence, ...layer3(reversal, continuation)];
}
