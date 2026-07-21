interface Props {
  label: string;
}

// Matches the exact placeholder pattern already used by the Watchlist and
// Reports pages for not-yet-built areas of the app.
export function ComingSoonPanel({ label }: Props) {
  return (
    <div className="flex items-center justify-center py-20">
      <p className="text-sm text-zinc-500">{label} — coming soon</p>
    </div>
  );
}
