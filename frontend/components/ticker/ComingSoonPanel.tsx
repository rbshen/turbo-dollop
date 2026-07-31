interface Props {
  label: string;
}

// Shared placeholder for not-yet-built areas of the app.
export function ComingSoonPanel({ label }: Props) {
  return (
    <div className="flex items-center justify-center py-20">
      <p className="text-sm text-text-tertiary">{label} — coming soon</p>
    </div>
  );
}
