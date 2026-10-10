import { cn } from "@/lib/utils";

/** A pulsing `surface-2` block in the shape of the content it stands in for (docs/design-system-charts.md, "States"). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden data-testid="skeleton" className={cn("animate-pulse rounded-md bg-surface-2", className)} />;
}

/** A row-shaped skeleton: a label block and a visual block, stacked on a narrow container like VisualRow. */
export function RowSkeleton({ rows = 1 }: { rows?: number }) {
  return (
    <div className="space-y-5" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="@container">
          <div className="flex flex-col gap-2 @xl:flex-row @xl:items-center @xl:gap-6">
            <Skeleton className="h-5 w-40 @xl:w-56" />
            <Skeleton className="h-4 flex-1" />
          </div>
        </div>
      ))}
    </div>
  );
}
