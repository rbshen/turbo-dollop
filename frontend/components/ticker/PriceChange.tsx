import { changeClass, fmtPct, fmtSignedMoney } from "@/lib/format";

interface Props {
  change: number | null;
  changePercent: number | null;
}

export function PriceChange({ change, changePercent }: Props) {
  if (change == null || changePercent == null) return null;
  const cls = changeClass(change);

  return (
    <span className={`font-mono text-sm tabular-nums ${cls}`}>
      {fmtSignedMoney(change)} ({fmtPct(changePercent)})
    </span>
  );
}
