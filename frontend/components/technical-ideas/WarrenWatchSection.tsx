"use client";

import { TechnicalIdeaSection } from "@/components/technical-ideas/TechnicalIdeaSection";
import { WarrenWatchTable } from "@/components/technical-ideas/WarrenWatchTable";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import type { WarrenWatchOut } from "@/lib/api/types";
import { useWarrenWatch } from "@/lib/hooks/useWarrenWatch";
import { fmtAsOf } from "@/lib/technicalIdeas";

const SKELETON_ROWS = 8;
const COLUMNS = 8;

interface Props {
  // Test seam: the section reads its own data (useWarrenWatch) unless a test passes a stand-in.
  useData?: () => { data?: WarrenWatchOut; error?: Error };
}

// "RSI WVF ADX by Warren" on 2h candles: the watch table of the latest Warren arrows per monitored ticker (docs/specs/warren-signals-page.md).
// Self-contained (its own data, states and footnote) so another strategy can sit beside it on the page.
export function WarrenWatchSection({ useData = useWarrenWatch }: Props) {
  const { data, error } = useData();

  return (
    <TechnicalIdeaSection
      title="RSI WVF ADX by Warren"
      tag="2h"
      asOf={data?.as_of ? fmtAsOf(data.as_of) : null}
      footnote={
        <>
          <p>
            One row per ticker on a monitored watchlist, kept after its last arrow until removed. All times are Eastern; a candle time is the
            start of its 2h window. Updated nightly, so the as-of stamp is the last completed candle.
          </p>
          <p>
            The stop follows the latest instruction, not the entry: it can sit above the entry price or move down. A watch note, not a
            trade record or advice.
          </p>
        </>
      }
    >
      {error && <p className="text-sm text-negative">Failed to load the Warren watch table.</p>}

      {!error && !data && (
        <Table>
          <TableBody>
            {Array.from({ length: SKELETON_ROWS }, (_, i) => (
              <TableRow key={i} className="animate-pulse bg-surface-2">
                <TableCell colSpan={COLUMNS} />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {!error && data && data.rows.length === 0 && (
        <p className="text-sm text-text-tertiary">
          No tickers on the watch table yet — a row appears when a Warren arrow fires on a monitored watchlist.
        </p>
      )}

      {!error && data && data.rows.length > 0 && <WarrenWatchTable rows={data.rows} />}
    </TechnicalIdeaSection>
  );
}
