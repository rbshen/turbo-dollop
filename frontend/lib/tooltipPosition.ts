// Pure geometry for InfoTooltip's fixed-position popover: centers the panel
// under its trigger icon by default, then clamps horizontally so it never
// crosses the viewport's left/right margins -- correct regardless of which
// column the icon sits in, without hardcoding per-column assumptions. The
// panel always opens ABOVE the icon (never below), which structurally
// avoids overlapping whatever field sits directly below the icon in a
// tightly-spaced form column.

export interface Rect {
  left: number;
  right: number;
  top: number;
}

export interface TooltipGeometry {
  panelLeft: number;
  panelTop: number;
  arrowLeft: number;
}

const ARROW_GAP = 10;
const ARROW_SIZE = 8;

export function computeTooltipGeometry(
  icon: Rect,
  panelWidth: number,
  panelHeight: number,
  viewportWidth: number,
  margin = 8,
): TooltipGeometry {
  const iconCenterX = (icon.left + icon.right) / 2;

  const desiredLeft = iconCenterX - panelWidth / 2;
  const minLeft = margin;
  const maxLeft = Math.max(minLeft, viewportWidth - panelWidth - margin);
  const panelLeft = Math.min(Math.max(desiredLeft, minLeft), maxLeft);

  const panelTop = icon.top - panelHeight - ARROW_GAP;

  const arrowMargin = 8;
  const minArrowLeft = arrowMargin;
  const maxArrowLeft = Math.max(minArrowLeft, panelWidth - arrowMargin - ARROW_SIZE);
  const desiredArrowLeft = iconCenterX - panelLeft - ARROW_SIZE / 2;
  const arrowLeft = Math.min(Math.max(desiredArrowLeft, minArrowLeft), maxArrowLeft);

  return { panelLeft, panelTop, arrowLeft };
}
