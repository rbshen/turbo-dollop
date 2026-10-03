import type { UniverseStatusOut } from "@/lib/api/types";

export type UniverseAction = "add" | "remove";

/** The one button the header shows for the universe, from the status response alone (docs/specs/tracked-universe.md,
 * "Frontend"): "add" for a browsed ticker that can be added, "remove" for an added ticker that is in the universe and has
 * no protection, and `null` (nothing at all) for everything else: no status yet (loading or failed), kind unknown,
 * delisted, protected (membership already shows in the header's index chip), a browsed ticker that cannot be added
 * (non-US), and an added ticker that is not actually in the universe. "In universe" is gated on `in_universe`, never on
 * `state`. There is no label: the Remove button itself is the indicator. */
export function universeAction(status: UniverseStatusOut | null | undefined): UniverseAction | null {
  if (!status || status.kind === null || status.delisted) return null;
  if (status.state === "browsed") return status.can_add ? "add" : null;
  if (status.state === "added") return status.can_remove && status.in_universe ? "remove" : null;
  return null;
}
