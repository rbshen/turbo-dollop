/** "40s ago" / "3m ago" / "14d ago" -- no existing helper in this codebase
 * covers this (ChecklistCard.tsx's fmtSwingDate is absolute-date only).
 * Shared by the Settings "Status" section's per-source/per-job timestamps
 * and its own header "Updated X ago" caption. */
export function formatRelativeTime(iso: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));

  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
