// How many rows of a Screener response are stale: scored with older weights than the saved ones (their weights_version is lower than the
// current one), or under another Overall FORMULA version (formula_version differs; null = scored before the Moat multiplier formula).
// A row with no weights_version was scored before weights were adjustable, with the defaults: its weights are not counted stale (the
// backend's header check treats it the same way); its formula version still is.
export function staleWeightsCount(
  rows: { weights_version?: number | null; formula_version?: number | null }[] | undefined,
  currentVersion: number | undefined,
  currentFormulaVersion?: number,
): number {
  if (!rows || currentVersion === undefined) return 0;
  return rows.filter(
    (row) =>
      (row.weights_version != null && row.weights_version < currentVersion) ||
      (currentFormulaVersion !== undefined && row.formula_version !== currentFormulaVersion),
  ).length;
}

export function staleWeightsMessage(count: number): string {
  return count === 1 ? "1 score is still on the previous weights" : `${count} scores are still on the previous weights`;
}
