import type { UniverseStatusOut } from "@/lib/api/types";

// Short labels for the reason codes the universe status API returns (`reasons[]`; produced by
// backend data/tracked_universe.py::load_protection_reasons, labels in data/ticker_data_registry.py::MANUAL_DATA_LABELS).
// Exact codes first, then the two prefixed families (`index:`, `watchlist:`, `manual:`). `delisted` is a classification,
// not a protection, so the API never sends it in `reasons`; it is here only so a stray one reads well.
const REASON_LABELS: Record<string, string> = {
  "index:sp500": "S&P 500",
  "index:nasdaq": "Nasdaq-100",
  "index:dow": "Dow",
  seed: "Seed ETF",
  benchmark: "Benchmark",
  rs_benchmark: "RS benchmark",
  "manual:moat": "Moat",
  "manual:custom_valuation": "Custom valuation",
  "manual:bank_capital": "Bank capital",
  "manual:growth_note": "Growth note",
  delisted: "Delisted",
};

/** A readable label for one reason code. A `watchlist:<name>` code reads "Watchlist <name>"; any code the map does not
 * know prints as the raw code, so a new backend code is visible rather than silently blank. */
export function universeReasonLabel(code: string): string {
  const known = REASON_LABELS[code];
  if (known) return known;
  if (code.startsWith("watchlist:") && code.length > "watchlist:".length) return `Watchlist ${code.slice("watchlist:".length)}`;
  return code;
}

export function universeReasonsText(reasons: string[]): string {
  return reasons.map(universeReasonLabel).join(", ");
}

export type UniverseDisplay =
  | { mode: "add" }
  | { mode: "remove" }
  | { mode: "protected"; reasons: string[] };

/** What the header shows about the universe, from the status response alone (docs/specs/tracked-universe.md,
 * "Frontend"). `null` = nothing at all: no status yet (loading or failed), kind unknown, delisted, a browsed ticker that
 * cannot be added (non-US), and a protected ticker that is not actually in the universe. "In universe" wording is
 * always gated on `in_universe`, never on `state`. */
export function universeDisplay(status: UniverseStatusOut | null | undefined): UniverseDisplay | null {
  if (!status || status.kind === null || status.delisted) return null;
  if (status.state === "browsed") return status.can_add ? { mode: "add" } : null;
  if (!status.in_universe) return null;
  if (status.state === "added") return status.can_remove ? { mode: "remove" } : null;
  return { mode: "protected", reasons: status.reasons };
}
