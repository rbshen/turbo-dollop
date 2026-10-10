"use client";

import Link from "next/link";
import { useState } from "react";
import { mutate } from "swr";

import { Button } from "@/components/ui/button";
import { Section } from "@/components/ui/section";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiPost, errorDetail } from "@/lib/api/client";
import type { DataQualityScope } from "@/lib/api/types";
import {
  COMPARISON_LABELS,
  checkLabel,
  fieldLabel,
  fmtFlagValue,
  foundDate,
  kindLabel,
} from "@/lib/dataQualityFlags";
import { useDataQualityFlags } from "@/lib/hooks/useDataQualityFlags";

const SCOPE_OPTIONS = [
  { value: "watchlisted", label: "Watchlisted" },
  { value: "all", label: "All tickers" },
];

/** Settings > Data quality (docs/specs/data-quality.md): the open cache-only flags about FMP statement rows, newest first. A plain table with
 * a "Mark reviewed" button per row. Informational: nothing here changes a score, and there is no banner or pill. The nightly job
 * (3:26 AM) fills and clears the list; a failed run shows in Scheduled jobs. */
export function DataQualitySection() {
  const [scope, setScope] = useState<DataQualityScope>("watchlisted");
  const { data, error } = useDataQualityFlags(scope);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function markReviewed(id: number) {
    setBusyId(id);
    setActionError(null);
    try {
      await apiPost(`/data-quality/flags/${id}/review`);
      await mutate((key) => typeof key === "string" && key.startsWith("/data-quality/flags"));
      await mutate((key) => typeof key === "string" && key.endsWith("/data-quality"));
    } catch (e) {
      setActionError(errorDetail(e) ?? "Could not mark the flag reviewed.");
    } finally {
      setBusyId(null);
    }
  }

  const open = data ? (scope === "watchlisted" ? data.open_watchlisted : data.open_all) : null;
  const otherOpen = data ? (scope === "watchlisted" ? data.open_all : data.open_watchlisted) : null;

  return (
    <Section>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-text-primary">
          Data quality
          {open !== null && <span className="ml-2 text-xs font-normal text-text-tertiary">{open} open</span>}
        </h3>
        <SegmentedControl
          aria-label="Tickers shown"
          value={scope}
          onValueChange={(next) => setScope(next as DataQualityScope)}
          options={SCOPE_OPTIONS}
        />
      </div>
      <p className="mt-2 max-w-xl text-sm text-text-secondary">
        Findings about FMP&apos;s cached statements, checked every night from the cache alone. They are context for reading a ticker&apos;s
        numbers: nothing here changes a score or a verdict.
      </p>

      {error ? (
        <p className="mt-3 text-sm text-negative">Could not load the data-quality flags.</p>
      ) : !data ? (
        <p className="mt-3 animate-pulse text-sm text-text-tertiary">Loading…</p>
      ) : (
        <>
          <Table className="mt-3 table-fixed">
            <colgroup>
              <col className="w-20" />
              <col className="w-[34%]" />
              <col className="w-24" />
              <col className="w-20" />
              <col className="w-24" />
              <col />
              <col className="w-28" />
            </colgroup>
            <TableHeader>
              <TableRow className="h-9">
                <TableHead>Ticker</TableHead>
                <TableHead>Check</TableHead>
                <TableHead>Fiscal year</TableHead>
                <TableHead className="text-right">FMP</TableHead>
                <TableHead className="text-right">Compared</TableHead>
                <TableHead>Kind and found</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.flags.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="whitespace-normal py-4 text-sm text-text-tertiary">
                    {scope === "watchlisted"
                      ? "No open flags on your watchlisted tickers."
                      : "No open flags."}
                    {scope === "watchlisted" && otherOpen ? ` ${otherOpen} open on other tracked tickers (All tickers).` : ""}
                  </TableCell>
                </TableRow>
              ) : (
                data.flags.map((flag) => (
                  <TableRow key={flag.id}>
                    <TableCell className="font-mono text-xs text-text-primary">
                      <Link href={`/tickers/${flag.ticker}`} className="hover:underline">
                        {flag.ticker}
                      </Link>
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      <div className="text-text-primary">
                        {checkLabel(flag.check)} <span className="text-text-secondary">· {fieldLabel(flag.field)}</span>
                      </div>
                      <div className="text-xs text-text-tertiary">{flag.detail}</div>
                    </TableCell>
                    <TableCell className="font-mono text-xs tabular-nums text-text-secondary">FY{flag.fiscal_year}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums text-text-primary">{fmtFlagValue(flag.fmp_value)}</TableCell>
                    <TableCell
                      className="text-right font-mono text-xs tabular-nums text-text-secondary"
                      title={COMPARISON_LABELS[flag.check]}
                    >
                      {fmtFlagValue(flag.comparison_value)}
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      <div className="text-xs text-warn">{kindLabel(flag.kind)}</div>
                      <div className="font-mono text-[11px] text-text-tertiary">{foundDate(flag.found_at)}</div>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busyId === flag.id}
                        onClick={() => markReviewed(flag.id)}
                        aria-label={`Mark reviewed: ${flag.ticker}, ${checkLabel(flag.check)}, FY${flag.fiscal_year}`}
                      >
                        Mark reviewed
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          {actionError && (
            <p role="alert" className="mt-2 text-xs text-negative">
              {actionError}
            </p>
          )}
        </>
      )}
    </Section>
  );
}
