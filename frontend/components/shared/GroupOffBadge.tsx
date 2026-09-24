"use client";

import { asOfText, offGroupsFor, reasonText } from "@/lib/dataGroups";
import { useDataGroups } from "@/lib/hooks/useDataGroups";

interface Props {
  /** Data-group keys (core/data_groups.py) that feed the page/section. */
  groups: readonly string[];
}

/** Small "not refreshing — as of [date]" badge for a page fed by an FMP data
 * group that is currently off (cache-only). Renders nothing while every
 * group is live, while loading, and for groups not wired to any feature yet. */
export function GroupOffBadge({ groups }: Props) {
  const { data } = useDataGroups();
  const off = offGroupsFor(data, groups);
  if (off.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 pt-2" data-testid="group-off-badge">
      {off.map((g) => (
        <span
          key={g.key}
          title={reasonText(g)}
          className="rounded-full border border-warn/40 bg-warn/16 px-2.5 py-0.5 text-xs font-medium text-warn"
        >
          {g.label}: not refreshing — as of {asOfText(g)}
        </span>
      ))}
    </div>
  );
}
