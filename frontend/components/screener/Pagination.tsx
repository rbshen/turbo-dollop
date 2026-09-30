import { CaretLeft, CaretRight } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  page: number;
  nPages: number;
  onPage: (p: number) => void;
}

export function Pagination({ page, nPages, onPage }: Props) {
  if (nPages <= 1) return null;

  const pages: (number | null)[] = [];
  for (let i = 1; i <= nPages; i++) {
    if (i === 1 || i === nPages || Math.abs(i - page) <= 2) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== null) {
      pages.push(null);
    }
  }

  return (
    <div className="flex items-center justify-center gap-1">
      <Button variant="ghost" size="sm" onClick={() => onPage(page - 1)} disabled={page === 1} aria-label="Previous page">
        <CaretLeft size={12} weight="bold" aria-hidden="true" />
        Prev
      </Button>
      {pages.map((p, i) =>
        p === null ? (
          <span key={`ellipsis-${i}`} className="px-1 text-text-tertiary">
            …
          </span>
        ) : (
          // The current page is the neutral selected treatment the segmented
          // control uses (surface-2 fill, text-primary), never brand blue.
          <Button
            key={p}
            variant="ghost"
            size="sm"
            onClick={() => onPage(p)}
            aria-current={p === page ? "page" : undefined}
            className={cn("px-2.5", p === page && "bg-surface-2 font-semibold text-text-primary")}
          >
            {p}
          </Button>
        )
      )}
      <Button variant="ghost" size="sm" onClick={() => onPage(page + 1)} disabled={page === nPages} aria-label="Next page">
        Next
        <CaretRight size={12} weight="bold" aria-hidden="true" />
      </Button>
    </div>
  );
}
