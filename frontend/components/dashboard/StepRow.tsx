import type { ReactNode } from "react";

import { VisualRow } from "@/components/charts/VisualRow";
import { Status } from "@/components/ui/status";
import { stepPill, type StepPill } from "@/lib/dashboard";

/** A step's stored score (plain, mono) beside its pill: the Analysis cards' convention, "74 [Pass with caution]". */
export function StepPillView({ pill }: { pill: StepPill }) {
  return (
    <span className="inline-flex items-center gap-2" data-testid="step-pill">
      {pill.score != null && <span className="font-mono text-sm tabular-nums text-text-primary">{pill.score}</span>}
      <Status tone={pill.tone}>{pill.label}</Status>
    </span>
  );
}

interface Props {
  name: string;
  storedScore: number | null;
  storedVerdict: string | null;
  kind?: "default" | "debt";
  children: ReactNode;
}

/** One scored step: name + pill on the left, its small visual on the right (stacked on a narrow container). The pill is the STORED
 * verdict, so it matches the header and the Screener; nothing is recomputed. */
export function StepRow({ name, storedScore, storedVerdict, kind = "default", children }: Props) {
  return (
    <div className="border-t border-border-subtle py-4 first:border-t-0" data-testid={`step-row-${name.toLowerCase()}`}>
      <VisualRow label={name} pill={<StepPillView pill={stepPill(storedScore, storedVerdict, kind)} />}>
        {children}
      </VisualRow>
    </div>
  );
}
