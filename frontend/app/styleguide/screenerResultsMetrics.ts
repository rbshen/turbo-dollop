// Computed (not measured) sizes for the Screener results controls reference.
// No browser was available, so every width is derived: text widths are summed
// glyph advance widths from the app's own font (Public Sans, the variable font
// instanced at weight 400 or 500, read with fontTools; no kerning), button
// widths add px-3 (2 x 12px) and the 1px outline border (2 x 1px), and a
// 222px row is the sidebar card's content width (256px minus 2px borders and
// 2 x 16px padding). The saved-views bar actually sits outside the cards, at
// the sidebar's full 256px, so 222px is the tighter case.
/** Width tokens of the boxed Select (lib/formControl.ts). */
export const SELECT_MEDIUM_WIDTH = 176;
export const SELECT_WIDE_WIDTH = 320;
/** A Select's text room is its width minus the 1px borders, pl-3 (12px) and pr-8 (32px, the caret). */
export const SELECT_TEXT_INSET = 2 + 12 + 32;
export function selectTextRoom(width: number): number {
  return width - SELECT_TEXT_INSET;
}

/** The longest Sort option label at 14px, weight 400. */
export const LONGEST_SORT_LABEL = { text: "Warren signal recency", width: 146.3 };

/** text-xs (12px) weight-500 label width + px-3 + borders, for the outline sm buttons. */
export const BUTTON_WIDTH = {
  save: 53.7,
  saveFailed: 88.8,
  cancel: 65.1,
  overwrite: 81.4,
} as const;

/** The sort direction toggle at the default size: icon 14 + gap 8 + text (14px weight 500) + px-3 + borders. */
export const DIRECTION_BUTTON_WIDTH = { desc: 14 + 8 + 32.6 + 26, asc: 14 + 8 + 24.8 + 26 };

/** The overwrite message on one line (12px, weight 400), for "Quality compounders". */
export const OVERWRITE_MESSAGE_ONE_LINE = 405;

export const ROW_GAP = 8;
export function rowWidth(...widths: number[]): number {
  return widths.reduce((a, b) => a + b, 0) + ROW_GAP * (widths.length - 1);
}

/** Save/Cancel row, widest label ("Save failed"). */
export const NAMING_BUTTON_ROW = rowWidth(BUTTON_WIDTH.saveFailed, BUTTON_WIDTH.cancel);
/** Overwrite/Cancel row, widest label ("Save failed" replaces "Overwrite" after a failed save). */
export const OVERWRITE_BUTTON_ROW = rowWidth(Math.max(BUTTON_WIDTH.overwrite, BUTTON_WIDTH.saveFailed), BUTTON_WIDTH.cancel);
export function overwriteMessageLines(container: number): number {
  return Math.ceil(OVERWRITE_MESSAGE_ONE_LINE / container);
}
