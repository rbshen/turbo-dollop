import { CaretDown, CheckCircle, XCircle } from "@phosphor-icons/react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

/** "Aug 12, 2026" -- shared by Reversal/Trend Continuation's swing-date
 * details, mirroring ValuationGauge.tsx's own inline toLocaleDateString
 * convention (this app has no shared fmtDate helper). */
export function fmtSwingDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export interface ChecklistItem {
  key: string;
  label: string;
  /** Boolean rows (most checklist items) render a check/x icon.
   * Status-only rows (e.g. Trend Continuation's "Resolution status", which
   * isn't a pass/fail check) omit `met` and set `statusText`/`toneClass`
   * instead. */
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
  statusToneClass: string;
  blurb: string;
  items: ChecklistItem[];
  /** Rendered below the checklist -- e.g. Trend Continuation's freshness
   * bar. Optional since Reversal has no equivalent. */
  extra?: React.ReactNode;
  /** The backtest-result caveat, shown directly on the card per this
   * feature's own "informational, not a trading signal" requirement --
   * never hidden behind a collapsible the way AnalysisSectionCard's
   * reasoning bullets are. */
  disclaimer: string;
  /** When true, the checklist items render inside a Collapsible (same
   * primitive AnalysisSectionCard uses for its reasoning bullets),
   * collapsed by default with a "Show details +"/"Hide details -" toggle.
   * Defaults to false -- Reversal/Trend Continuation stay always-expanded,
   * unchanged from their original design (see the removed comment this
   * replaced: those two cards' own status pill is the at-a-glance signal,
   * so their few items were always meant to be visible immediately).
   * Weinstein Stage Analysis is the one consumer that opts in, since its
   * checklist is longer and mostly supporting detail behind the stage
   * pill itself. */
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

export function ChecklistCard({ title, statusLabel, statusToneClass, blurb, items, extra, disclaimer, collapsible = false }: Props) {
  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 className="font-heading text-sm font-semibold text-text-primary">{title}</h2>
          <p className="text-sm text-text-secondary">{blurb}</p>
        </div>
        <span className={`shrink-0 rounded-full border px-3 py-1 text-xs font-semibold ${statusToneClass}`}>{statusLabel}</span>
      </div>

      {collapsible ? (
        <Collapsible>
          <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-text-tertiary">
            <span className="group-data-[panel-open]:hidden">Show details +</span>
            <span className="hidden group-data-[panel-open]:inline">Hide details −</span>
            <CaretDown size={12} className="transition-transform duration-200 group-data-[panel-open]:rotate-180" />
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
