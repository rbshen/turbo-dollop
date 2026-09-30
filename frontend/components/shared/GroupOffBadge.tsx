"use client";

import { Status } from "@/components/ui/status";
import { asOfText, offGroupsFor, reasonText } from "@/lib/dataGroups";
import { useDataGroups } from "@/lib/hooks/useDataGroups";
import { pillLabel } from "@/lib/tierColor";

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
        <Status key={g.key} tone="warn" title={reasonText(g)}>
          {pillLabel(g.label)}: not refreshing — as of {asOfText(g)}
        </Status>
      ))}
    </div>
  );
}
