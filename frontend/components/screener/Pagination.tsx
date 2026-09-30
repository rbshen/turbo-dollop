import { Button } from "@/components/ui/button";

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
      <Button variant="ghost" size="sm" onClick={() => onPage(page - 1)} disabled={page === 1}>
        « Prev
      </Button>
      {pages.map((p, i) =>
        p === null ? (
          <span key={`ellipsis-${i}`} className="px-1 text-text-tertiary">
            …
          </span>
        ) : (
          <Button
            key={p}
            variant={p === page ? "primary" : "ghost"}
            size="sm"
            onClick={() => onPage(p)}
            className={p === page ? "px-2.5 font-semibold" : "px-2.5"}
          >
            {p}
          </Button>
        )
      )}
      <Button variant="ghost" size="sm" onClick={() => onPage(page + 1)} disabled={page === nPages}>
        Next »
      </Button>
    </div>
  );
}
