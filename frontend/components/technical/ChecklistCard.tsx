import { CaretDown, CaretUp, CheckCircle, XCircle } from "@phosphor-icons/react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Status, type StatusTone } from "@/components/ui/status";
import { pillLabel } from "@/lib/tierColor";

/** "Aug 12, 2026" -- shared by the Weinstein card's since-date details,
 * mirroring ValuationGauge.tsx's own inline toLocaleDateString
 * convention (this app has no shared fmtDate helper). */
export function fmtSwingDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export interface ChecklistItem {
  key: string;
  label: string;
  /** Boolean rows (most checklist items) render a check/x icon.
   * Status-only rows (not a pass/fail check) omit `met` and set
   * `statusText`/`toneClass` instead. */
  met?: boolean;
  statusText?: string;
  toneClass?: string;
  /** Secondary line under the label -- the actual date/ratio/tier backing
   * this row, so the checklist reads as evidence, not just a claim. */
  detail?: string;
}

interface Props {
  title: string;
  statusLabel: string;
  statusTone: StatusTone;
  blurb: string;
  items: ChecklistItem[];
  /** Rendered below the checklist -- e.g. the Weinstein card's pending block. */
  extra?: React.ReactNode;
  /** The backtest-result caveat, shown directly on the card per this
   * feature's own "informational, not a trading signal" requirement --
   * never hidden behind a collapsible the way AnalysisSectionCard's
   * reasoning bullets are. */
  disclaimer: string;
  /** When true, the checklist items render inside a Collapsible (same
   * primitive AnalysisSectionCard uses for its reasoning bullets),
   * expanded by default (2026-10-09), with a "Hide details"/"Show details" toggle.
   * Defaults to false (always-expanded). Weinstein Stage Analysis opts in,
   * since its checklist is longer and mostly supporting detail behind the
   * stage pill itself. */
  collapsible?: boolean;
}

function ChecklistItems({ items }: { items: ChecklistItem[] }) {
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.key} className="flex items-start gap-2 text-sm">
          {item.met !== undefined ? (
            item.met ? (
              <CheckCircle size={16} weight="fill" className="mt-0.5 shrink-0 text-positive" />
            ) : (
              <XCircle size={20} weight="fill" className="mt-0.5 shrink-0 text-text-tertiary" />
            )
          ) : (
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-text-tertiary" />
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-1.5">
              <span className="text-text-primary">{item.label}</span>
              {item.statusText && <span className={`text-xs font-medium ${item.toneClass ?? "text-text-tertiary"}`}>{item.statusText}</span>}
            </div>
            {item.detail && <p className="text-xs text-text-tertiary">{item.detail}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ChecklistCard({ title, statusLabel, statusTone, blurb, items, extra, disclaimer, collapsible = false }: Props) {
  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 className="font-heading text-sm font-semibold text-text-primary">{title}</h2>
          <p className="text-sm text-text-secondary">{blurb}</p>
        </div>
        <Status tone={statusTone} className="shrink-0">
          {pillLabel(statusLabel)}
        </Status>
      </div>

      {collapsible ? (
        <Collapsible defaultOpen>
          <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-text-tertiary">
            <span className="group-data-[panel-open]:hidden">Show details</span>
            <span className="hidden group-data-[panel-open]:inline">Hide details</span>
            <CaretDown size={12} aria-hidden="true" className="group-data-[panel-open]:hidden" />
            <CaretUp size={12} aria-hidden="true" className="hidden group-data-[panel-open]:block" />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mt-3">
              <ChecklistItems items={items} />
            </div>
          </CollapsibleContent>
        </Collapsible>
      ) : (
        <ChecklistItems items={items} />
      )}

      {extra}

      <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs text-warn">{disclaimer}</p>
    </div>
  );
}
