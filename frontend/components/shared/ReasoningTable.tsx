import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface ReasoningTableRow {
  key: string;
  label: string;
  tierLabel: string;
  tierClassName: string;
  weight?: number;
  contribution?: number;
}

interface Props {
  rows: ReasoningTableRow[];
  /** "Metric" (Step 1/2/4) or "Ratio" (Step 5) -- the shared header text differs by step. */
  labelHeader?: string;
  /** Step 4's table has no per-component weight/contribution breakdown, unlike Step 1/2/5. */
  showWeightContribution?: boolean;
}

// Shared score-explanation table, used by Step1Card/Step2Card/Step5Card
// (all identical 4-column Metric-or-Ratio/Tier/Weight/Contribution shape)
// and Step4Card (the same idea, minus the Weight/Contribution columns).
export function ReasoningTable({ rows, labelHeader = "Metric", showWeightContribution = true }: Props) {
  return (
    <Table className="w-full border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="border-b border-zinc-800 py-2 pr-4 font-medium">{labelHeader}</TableHead>
          <TableHead
            className={`border-b border-zinc-800 py-2 font-medium ${showWeightContribution ? "pr-4 text-left" : "pr-0 text-right"}`}
          >
            Tier
          </TableHead>
          {showWeightContribution && (
            <>
              <TableHead className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">Weight</TableHead>
              <TableHead className="border-b border-zinc-800 py-2 text-right font-medium">Contribution</TableHead>
            </>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.key} className="hover:bg-transparent">
            <TableCell className="border-b border-zinc-900 py-2 pr-4 text-zinc-400">{row.label}</TableCell>
            <TableCell
              className={`border-b border-zinc-900 py-2 font-medium ${row.tierClassName} ${showWeightContribution ? "pr-4 text-left" : "text-right"}`}
            >
              {row.tierLabel}
            </TableCell>
            {showWeightContribution && (
              <>
                <TableCell className="border-b border-zinc-900 py-2 pr-4 text-right text-zinc-400">
                  {row.weight != null ? `${Math.round(row.weight * 100)}%` : "—"}
                </TableCell>
                <TableCell className="border-b border-zinc-900 py-2 text-right text-zinc-100">
                  {row.contribution != null ? `${row.contribution} pts` : "—"}
                </TableCell>
              </>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
