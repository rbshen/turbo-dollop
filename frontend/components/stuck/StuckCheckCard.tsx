"use client";

import { GroupOffBadge } from "@/components/shared/GroupOffBadge";
import { Badge } from "@/components/ui/badge";
import { Status } from "@/components/ui/status";
import type { StuckRow } from "@/lib/api/types";
import { useStuckCheck } from "@/lib/hooks/useStuckCheck";
import { formatFigure, rowsForGroup, STATUS_LABEL, STUCK_GROUPS } from "@/lib/stuckCheck";

// Price rows read cached daily bars; when that group is paused the card still shows what is cached (the Analysis tab's own badge
// covers fundamentals).
const PRICE_GROUPS = ["daily_prices"] as const;

function StatusTag({ row }: { row: StuckRow }) {
  if (row.status == null) return null;
  // Flagged is a plain amber tag; every other label is a quiet neutral one. No red, no verdict wording.
  if (row.status === "flagged") return <Status tone="warn" size="compact">{STATUS_LABEL.flagged}</Status>;
  return (
    <Badge tone="neutral" size="compact" className={row.status === "ok" ? undefined : "text-text-tertiary"}>
      {STATUS_LABEL[row.status]}
    </Badge>
  );
}

function RowView({ row, currency }: { row: StuckRow; currency: string }) {
  return (
    <li className="space-y-2 py-3" data-testid={`stuck-row-${row.key}`}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium text-text-primary">{row.title}</h3>
        <StatusTag row={row} />
      </div>
      {row.reason && <p className="text-xs text-text-tertiary">{row.reason}</p>}
      {row.figures.length > 0 && (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 min-[420px]:grid-cols-2 lg:grid-cols-3">
          {row.figures.map((figure) => (
            <div key={figure.key} className="min-w-0">
              <dt className="text-xs text-text-tertiary">{figure.label}</dt>
              <dd className="font-mono text-sm tabular-nums text-text-primary">{formatFigure(figure, currency)}</dd>
            </div>
          ))}
        </dl>
      )}
      {row.notes.map((note) => (
        <p key={note} className="text-xs text-text-secondary">
          {note}
        </p>
      ))}
    </li>
  );
}

/** "Why might it be stuck?" -- the bottom card of the Analysis tab. Informational: no score, no verdict, no summary count; it feeds
 * nothing. Cache-only on the server. */
export function StuckCheckCard({ ticker }: { ticker: string }) {
  const { data, error, isLoading } = useStuckCheck(ticker);

  const shell = (body: React.ReactNode) => (
    <section aria-labelledby="stuck-check-title" className="rounded-lg border border-border-card bg-surface p-6">
      <div className="space-y-1">
        <h2 id="stuck-check-title" className="font-heading text-sm font-semibold text-text-primary">
          Why might it be stuck?
        </h2>
        <p className="text-xs text-text-tertiary">{data?.subtitle ?? "Context, not scored"}</p>
      </div>
      <GroupOffBadge groups={PRICE_GROUPS} />
      {body}
    </section>
  );

  if (error) return shell(<p className="mt-4 text-sm text-negative">Couldn&apos;t load this card — {error.message}</p>);
  if (isLoading || !data) return shell(<p className="mt-4 animate-pulse text-sm text-text-tertiary">Loading…</p>);
  if (!data.applicable) return null; // an ETF/fund: the stock tabs (and this card) are not shown for it
  if (data.rows.length === 0) {
    return shell(<p className="mt-4 text-sm text-text-secondary">Nothing is cached for this ticker yet, so there is nothing to show.</p>);
  }

  return shell(
    <div className="mt-4 space-y-6">
      {!data.has_data && (
        <p className="text-sm text-text-secondary">
          No cached financial statements for this ticker yet, so only the stored price context is shown.
        </p>
      )}
      {STUCK_GROUPS.map((group) => {
        const rows = rowsForGroup(data.rows, group.numbers);
        if (rows.length === 0) return null;
        return (
          <div key={group.key}>
            <h3 className="pb-1 text-xs font-semibold text-text-secondary">{group.title}</h3>
            <ul className="divide-y divide-border-subtle border-t border-border-subtle">
              {rows.map((row) => (
                <RowView key={row.key} row={row} currency={data.currency} />
              ))}
            </ul>
          </div>
        );
      })}
      {data.footer && <p className="text-sm text-text-secondary">{data.footer}</p>}
    </div>,
  );
}
