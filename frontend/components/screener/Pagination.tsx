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
      <button
        onClick={() => onPage(page - 1)}
        disabled={page === 1}
        className="rounded px-2 py-1 text-sm text-text-secondary transition-colors hover:text-text-primary disabled:opacity-30"
      >
        « Prev
      </button>
      {pages.map((p, i) =>
        p === null ? (
          <span key={`ellipsis-${i}`} className="px-1 text-text-tertiary">
            …
          </span>
        ) : (
          <button
            key={p}
            onClick={() => onPage(p)}
            className={`rounded px-2.5 py-1 text-sm transition-colors ${
              p === page ? "bg-brand font-semibold text-white" : "text-text-secondary hover:bg-surface-2 hover:text-text-primary"
            }`}
          >
            {p}
          </button>
        )
      )}
      <button
        onClick={() => onPage(page + 1)}
        disabled={page === nPages}
        className="rounded px-2 py-1 text-sm text-text-secondary transition-colors hover:text-text-primary disabled:opacity-30"
      >
        Next »
      </button>
    </div>
  );
}
