import type { MouseEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { OpportunityListName, OpportunityRowOut } from "@/lib/api/types";
import { fmtPct, pnlClass } from "@/lib/format";
import { fmtAdvM, MAX_TAG_PILLS, rankTitle, tagPills, TIER_LABEL } from "@/lib/opportunities";
import { toneForNullable, verdictLabel } from "@/lib/tierColor";

const HEAD_CLASS = "text-xs font-medium text-text-tertiary";

interface Props {
  rows: OpportunityRowOut[];
  list: OpportunityListName;
  /** rule_id -> the label the Reversal tab shows in place of Weeks in Advance. */
  ruleLabels: Record<string, string>;
}

// The whole row opens the ticker page in a new tab (as the Momentum table and the Watchlist do); the ticker itself stays a real
// <a target="_blank"> for keyboard and middle-click, and a click that starts on it (or on any button) is left to the browser so
// two tabs never open.
function handleRowClick(e: MouseEvent<HTMLTableRowElement>, ticker: string) {
  if ((e.target as HTMLElement).closest("a, button")) return;
  window.open(`/tickers/${ticker}`, "_blank", "noopener,noreferrer");
}

function VerdictCell({ row }: { row: OpportunityRowOut }) {
  if (!row.overall_verdict) return <Badge size="compact" missing title={row.tier === "etf" ? "Funds are not scored" : "Overall incomplete"} />;
  return (
    <Badge size="compact" tone={toneForNullable(row.overall_score, row.overall_verdict)} title={row.overall_score != null ? `Overall ${row.overall_score}` : undefined}>
      {verdictLabel(row.overall_verdict)}
    </Badge>
  );
}

function TagsCell({ row, list }: { row: OpportunityRowOut; list: OpportunityListName }) {
  const pills = tagPills(row, list);
  const shown = pills.slice(0, MAX_TAG_PILLS);
  const hidden = pills.slice(MAX_TAG_PILLS);
  return (
    <div className="flex flex-nowrap items-center gap-1">
      {shown.map((p) => (
        <Badge key={p.key} size="compact" tone={p.tone} title={p.title}>
          {p.label}
        </Badge>
      ))}
      {hidden.length > 0 && (
        <Badge size="compact" title={hidden.map((p) => `${p.label}${p.title ? ` — ${p.title}` : ""}`).join("\n")}>
          +{hidden.length}
        </Badge>
      )}
    </div>
  );
}

export function OpportunitiesTable({ rows, list, ruleLabels }: Props) {
  if (rows.length === 0) {
    return <p className="py-6 text-sm text-text-tertiary">Nothing on this list for the selected tier.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow className="h-9">
          <TableHead className={`${HEAD_CLASS} w-[260px]`}>Ticker</TableHead>
          <TableHead className={HEAD_CLASS}>Tier</TableHead>
          <TableHead className={HEAD_CLASS}>Verdict</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>vs MA</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Rank</TableHead>
          {list === "momentum" ? (
            <TableHead className={`${HEAD_CLASS} text-right`}>Weeks in Advance</TableHead>
          ) : (
            <TableHead className={HEAD_CLASS}>Rule</TableHead>
          )}
          <TableHead className={`${HEAD_CLASS} text-right`}>ADV $M</TableHead>
          <TableHead className={HEAD_CLASS}>Tags</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={`${row.list_name}-${row.ticker}`} interactive onClick={(e) => handleRowClick(e, row.ticker)}>
            <TableCell className="max-w-[260px] overflow-hidden">
              <a
                href={`/tickers/${row.ticker}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-sm font-semibold text-text-primary"
              >
                {row.ticker}
              </a>
              <p className="truncate text-xs text-text-secondary" title={row.company_name ?? undefined}>
                {row.company_name ?? "—"}
              </p>
            </TableCell>
            <TableCell>
              <Badge size="compact">{TIER_LABEL[row.tier]}</Badge>
            </TableCell>
            <TableCell>
              <VerdictCell row={row} />
            </TableCell>
            <TableCell className={`text-right font-mono ${row.vs_ma_pct != null ? pnlClass(row.vs_ma_pct) : "text-text-tertiary"}`}>
              {row.vs_ma_pct != null ? fmtPct(row.vs_ma_pct, 1) : "—"}
            </TableCell>
            <TableCell className="text-right font-mono text-text-secondary" title={rankTitle(row)}>
              {row.momentum_rank ?? "—"}
            </TableCell>
            {list === "momentum" ? (
              <TableCell className="text-right font-mono text-text-secondary">{row.weeks_in_advance ?? "—"}</TableCell>
            ) : (
              <TableCell>
                <div className="flex flex-nowrap items-center gap-1">
                  {row.rule_ids.map((id) => (
                    <Badge key={id} size="compact" title={id}>
                      {ruleLabels[id] ?? id}
                    </Badge>
                  ))}
                </div>
              </TableCell>
            )}
            <TableCell className="text-right font-mono text-text-secondary">{fmtAdvM(row.adv_usd)}</TableCell>
            <TableCell className="max-w-[420px] overflow-hidden">
              <TagsCell row={row} list={list} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
