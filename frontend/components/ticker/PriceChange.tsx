import { changeClass, fmtPct, fmtSignedMoney } from "@/lib/format";

interface Props {
  change: number | null;
  changePercent: number | null;
  currency?: string;
}

export function PriceChange({ change, changePercent, currency = "USD" }: Props) {
  if (change == null || changePercent == null) return null;
  const cls = changeClass(change);

  return (
    <span className={`font-mono text-sm tabular-nums ${cls}`}>
      {fmtSignedMoney(change, currency)} ({fmtPct(changePercent)})
    </span>
  );
}
