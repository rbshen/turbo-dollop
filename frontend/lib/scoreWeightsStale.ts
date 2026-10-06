// How many rows of a Screener response were scored with older weights than the saved ones (their weights_version is lower than the
// current one). A row with no version was scored before weights were adjustable, with the defaults: not counted (the backend's header
// check treats it the same way).
export function staleWeightsCount(rows: { weights_version?: number | null }[] | undefined, currentVersion: number | undefined): number {
  if (!rows || currentVersion === undefined) return 0;
  return rows.filter((row) => row.weights_version != null && row.weights_version < currentVersion).length;
}

export function staleWeightsMessage(count: number): string {
  return count === 1 ? "1 score is still on the previous weights" : `${count} scores are still on the previous weights`;
}
