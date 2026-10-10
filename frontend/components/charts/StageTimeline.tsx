import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import { cn } from "@/lib/utils";
import { groupStageRuns, stageSincePosition, type StageWeek } from "@/lib/chartGeometry";
import {
  formatWeinsteinSince,
  WEINSTEIN_LOWER_BOUND_CAVEAT,
  WEINSTEIN_STAGE_LABEL,
  WEINSTEIN_STAGE_TONE,
  type WeinsteinStage,
} from "@/lib/weinsteinStage";

interface Props {
  /** One entry per week, oldest first (the last ~12 months). */
  weeks: StageWeek[];
  /** ISO date the current stage began, and whether it is only a lower bound (the history starts there). */
  since?: string | null;
  sinceIsLowerBound?: boolean;
  /** Replaces the strip with the reason (fewer weeks cached than the engine needs). */
  unavailableReason?: string | null;
  className?: string;
}

// The same tones the WeinsteinStagePill draws (WEINSTEIN_STAGE_TONE), as fills: the strip and the header pill must always agree.
const FILL: Record<string, string> = {
  positive: "bg-positive",
  warn: "bg-warn",
  negative: "bg-negative",
  neutral: "bg-text-tertiary/40",
};

function fillFor(stage: string | null): string {
  if (!stage || !(stage in WEINSTEIN_STAGE_TONE)) return "bg-surface-2";
  return FILL[WEINSTEIN_STAGE_TONE[stage as WeinsteinStage]] ?? "bg-surface-2";
}

function monthYear(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

/** The last 12 months of Weinstein stage as one strip, a segment per run of equal stage, the switch date marked. */
export function StageTimeline({ weeks, since, sinceIsLowerBound = false, unavailableReason, className }: Props) {
  if (unavailableReason || weeks.length === 0) {
    return <p className={cn("text-xs text-text-tertiary", className)}>{unavailableReason ?? "No stage history yet"}</p>;
  }

  const runs = groupStageRuns(weeks);
  const marker = stageSincePosition(weeks, since);
  const shown = Array.from(new Set(runs.map((r) => r.stage).filter((s): s is string => !!s && s in WEINSTEIN_STAGE_LABEL)));
  const sinceText = since ? formatWeinsteinSince(since, sinceIsLowerBound, fmtSwingDate) : null;
  const current = runs[runs.length - 1].stage;
  const summary = [current && current in WEINSTEIN_STAGE_LABEL ? WEINSTEIN_STAGE_LABEL[current as WeinsteinStage] : null, sinceText].filter(Boolean).join(", ");

  return (
    <div role="img" aria-label={`Weinstein stage over the last ${weeks.length} weeks${summary ? `: ${summary}` : ""}`} className={cn("flex flex-col gap-1.5", className)}>
      <div className="relative pt-2">
        <div className="flex h-3 gap-px overflow-hidden rounded-sm">
          {runs.map((run) => (
            <div key={run.start} data-testid="stage-run" data-stage={run.stage ?? "none"} className={fillFor(run.stage)} style={{ flexGrow: run.weeks, flexBasis: 0 }} />
          ))}
        </div>
        {marker && (
          <div
            data-testid="stage-since-marker"
            data-inside={marker.inside}
            className="absolute inset-y-0 w-0.5 -translate-x-1/2 rounded-full bg-text-primary"
            style={{ left: `${marker.pct}%` }}
          />
        )}
      </div>
      <div className="flex justify-between text-xs text-text-tertiary">
        <span>{monthYear(weeks[0].week)}</span>
        <span>Now</span>
      </div>
      {sinceText && (
        <p className="text-xs text-text-secondary">
          {sinceText}
          {sinceIsLowerBound && <span className="text-text-tertiary"> — {WEINSTEIN_LOWER_BOUND_CAVEAT}</span>}
        </p>
      )}
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-tertiary">
        {shown.map((stage) => (
          <li key={stage} className="flex items-center gap-1.5">
            <span aria-hidden className={cn("size-2 rounded-sm", fillFor(stage))} />
            {WEINSTEIN_STAGE_LABEL[stage as WeinsteinStage]}
          </li>
        ))}
      </ul>
    </div>
  );
}
