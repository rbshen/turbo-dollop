interface Props {
  exchange: string;
}

export function ExchangeBadge({ exchange }: Props) {
  return (
    <span className="inline-flex items-center rounded-md border border-zinc-700/40 bg-zinc-800 px-1.5 py-0.5 text-xs font-semibold text-zinc-400">
      {exchange}
    </span>
  );
}
