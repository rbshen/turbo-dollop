// Computed (not measured) sizes for the Screener sidebar reference and its note.
// Everything is derived from the class tokens, at the 16px root the app uses:
//   text-xs line-height 1.0625rem = 17px, text-sm line-height 1.3125rem = 21px,
//   boxed field h-9 = 36px, label-to-control gap-0.5 = 2px, the range grid's
//   gap-y-3 = 12px, Card p-4 = 16px each side, 1px borders.
// (The pre-migration underline grid measured 555px on the live page,
// 9 x 51 + 8 x 12; the boxed grid with nine fields was 36px taller, 591px. Since
// 2026-10-08 the Overall field is a multi-select above the grid, so the grid holds
// eight fields: 524px, and 543px with the market-cap hint.)

export const SIDEBAR_WIDTH = 256;
/** Card content width: the sidebar minus 2 x 1px border and 2 x 16px padding. */
export const SIDEBAR_CONTENT_WIDTH = SIDEBAR_WIDTH - 2 - 32;

export const LABEL_ROW = 17;
export const LABEL_GAP = 2;
export const BOXED_BOX = 36;
export const FIELD_GRID_GAP = 12;
export const RANGE_COUNT = 8;
/** A hint line (text-xs) under a compact field: its line plus the 2px gap. */
export const HINT_ROW = LABEL_ROW + LABEL_GAP;
/** An error line under a pair adds the same. It shows only while there is an error. */
export const ERROR_ROW = LABEL_ROW + LABEL_GAP;

/** One label + 2px + box. */
export function rangeFieldHeight(): number {
  return LABEL_ROW + LABEL_GAP + BOXED_BOX;
}

/** The Overall verdict multi-select (a 32px item) above the grid, and the space-y-4 (16px) gap to the grid. */
export const OVERALL_SELECT_BLOCK = 32 + 16;

/** The eight-field range grid (no error lines; the market-cap hint is extra). */
export function rangeGridHeight(withMarketCapHint = false): number {
  return RANGE_COUNT * rangeFieldHeight() + (RANGE_COUNT - 1) * FIELD_GRID_GAP + (withMarketCapHint ? HINT_ROW : 0);
}

// Card chrome around the grid: 2px borders + 32px padding, the 21px title row,
// the 16px gap to the content (the Overall multi-select block sits above the grid), the space-y-4 (16px) to the multi-select block,
// its 1px top border + 12px top padding, and five 32px items (four multi-selects
// and the Speculative growth chip) with four 8px gaps.
const CARD_CHROME = 2 + 32 + 21 + 16;
const BELOW_GRID = 16 + 1 + 12 + (5 * 32 + 4 * 8);

/** The whole Fundamental card. */
export function fundamentalSectionHeight(withMarketCapHint = false): number {
  return CARD_CHROME + OVERALL_SELECT_BLOCK + rangeGridHeight(withMarketCapHint) + BELOW_GRID;
}

/** Width of a Min/Max pair: two 96px boxes, a dash between, two 6px gaps. The dash
 * is one en dash at 13px (about 7px); it is the only part that is an estimate. */
export const DASH_WIDTH = 7;
export const PAIR_WIDTH = 96 * 2 + 6 * 2 + DASH_WIDTH;
