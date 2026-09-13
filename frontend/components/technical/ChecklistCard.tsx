import { CaretDown, CheckCircle, XCircle } from "@phosphor-icons/react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

/** "Aug 12, 2026" -- shared by Reversal/Trend Continuation's swing-date
 * details, mirroring ValuationGauge.tsx's own inline toLocaleDateString
 * convention (this app has no shared fmtDate helper). */
export function fmtSwingDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Small uppercase section label, shared by Trend Continuation's "Right
 * now"/"Past cycles this trend" and Reversal's "Past candidates this
 * trend" sub-sections. */
export function SectionHeading({ children }: { children: React.ReactNode }) {
  return <p className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">{children}</p>;
}

export interface TimelineDot {
  key: string;
  date: string;
  /** Tailwind background color class for the dot itself, e.g. "bg-warn"
   * (pullback began), "bg-positive" (resolved / divergence present), or
   * "bg-border-subtle" (neutral / no divergence). */
  dotClassName: string;
  /** Hover tooltip explaining this specific dot. */
  title: string;
  /** Appended after the date as " · <caption>" -- e.g. "12 bars ago". */
  caption?: string;
}

/** A horizontal, horizontally-scrollable row of dated dots connected by
 * hairlines -- shared low-level shape behind both Trend Continuation's
 * pullback-cycle timeline (two-color alternating warning/resolved PAIRS)
 * and Reversal's reversal-candidate timeline (single-point events colored
 * by whether A/D Bullish Divergence was present). The two callers differ
 * in what a "point" means and how it's colored, not in this rendering
 * shape, so only the row-of-dots primitive is shared -- each card keeps
 * its own function for turning its own data into `dots`. Renders nothing
 * for an empty list, same "only show when meaningful" contract every
 * other piece of this timeline follows. */
export function DotTimeline({ dots }: { dots: TimelineDot[] }) {
  if (dots.length === 0) return null;
  return (
    <div className="flex items-start overflow-x-auto pb-1">
      {dots.map((dot, i) => (
        <div key={dot.key} className="flex items-center">
          {i > 0 && <div className="h-px w-4 shrink-0 bg-border-subtle" />}
          <div className="flex shrink-0 flex-col items-center gap-1">
            <span className={`h-2 w-2 rounded-full ${dot.dotClassName}`} title={dot.title} />
            <span className="whitespace-nowrap text-[10px] text-text-tertiary">
              {fmtSwingDate(dot.date)}
              {dot.caption ? ` · ${dot.caption}` : ""}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
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
