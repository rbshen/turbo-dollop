interface Props {
  exchange: string;
}

export function ExchangeBadge({ exchange }: Props) {
  return (
    <span className="inline-flex items-center rounded-md border border-border-input bg-surface-2 px-1.5 py-0.5 text-xs font-semibold text-text-secondary">
      {exchange}
    </span>
  );
}
