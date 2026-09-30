"use client";

// useDraftNumber -- the typed text of ONE side of a numeric filter, kept apart
// from the number it produces. The filter state stays numeric (so saved views
// and ScreenerFilterState never change); the text a user is half-way through
// typing lives only here.
//
// Commit rule, per side (docs/design-system.md "RangeField"):
//   - valid text commits at once, including "12." and ".5";
//   - an incomplete prefix ("-", ".", "-.") HOLDS the previous committed value
//     with no error while the box is focused, and is invalid once it is not
//     (blur emits null so the filter matches what the error says);
//   - any other invalid text (letters, "1x", "5e", below `min`) makes the side
//     inactive at once (emits null) and reports an error;
//   - nothing is ever clamped, swapped or corrected.
//
// Re-sync: the hook never rewrites what the user is typing, but an EXTERNAL
// change (Reset, Load saved view, a remount) must update the box. The pair
// object `owner` that holds this side's value is compared by IDENTITY with
// `lastEmitted`, the exact object this field last emitted (the ref is shared
// by both sides of a pair). A different object from outside re-syncs the draft
// even when its numbers are equal to the current ones, so stale invalid text
// such as "1x" is cleared by a Reset. The parent must therefore hand the
// emitted object back unchanged.
import { useState, type MutableRefObject } from "react";
import {
  checkNumber,
  formatNumberInput,
  isIncompleteNumberPrefix,
  type NumberRules,
  type NumberSuffixes,
} from "@/lib/numberInput";

/** What the owner should do after a keystroke or blur: nothing, or emit this value. */
export type DraftOutcome = { emit: false } | { emit: true; value: number | null };

export interface UseDraftNumberOptions {
  /** The committed numeric value for this side. */
  value: number | null;
  /** The object that holds `value` (the pair). Compared by identity. */
  owner: unknown;
  /** The object this field last emitted (null until it has emitted one); set by the owner
   * just before it calls onChange. Start it at null, never at the mounted value. */
  lastEmitted: MutableRefObject<unknown>;
  suffixes?: NumberSuffixes;
  min?: number;
}

export interface DraftNumber {
  draft: string;
  /** The error to show for this side's text, or null (a held prefix has none). */
  error: string | null;
  change: (text: string) => DraftOutcome;
  focus: () => void;
  blur: () => DraftOutcome;
}

export function useDraftNumber({ value, owner, lastEmitted, suffixes, min }: UseDraftNumberOptions): DraftNumber {
  const rules: NumberRules = { optional: true, suffixes, min };
  const [draft, setDraft] = useState(() => formatNumberInput(value, suffixes));
  const [focused, setFocused] = useState(false);
  const [seenOwner, setSeenOwner] = useState(owner);

  if (owner !== seenOwner) {
    setSeenOwner(owner);
    if (owner !== lastEmitted.current) setDraft(formatNumberInput(value, suffixes));
  }

  const check = checkNumber(draft, rules);
  const held = focused && isIncompleteNumberPrefix(draft);

  return {
    draft,
    error: check.error && !held ? check.error : null,
    change(text) {
      setDraft(text);
      // A change can only come from typing in the box, so it is focused.
      setFocused(true);
      if (isIncompleteNumberPrefix(text)) return { emit: false };
      const next = checkNumber(text, rules);
      return { emit: true, value: next.error ? null : next.value };
    },
    focus() {
      setFocused(true);
    },
    blur() {
      setFocused(false);
      return isIncompleteNumberPrefix(draft) ? { emit: true, value: null } : { emit: false };
    },
  };
}
