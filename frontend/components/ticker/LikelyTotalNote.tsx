import type { LikelyTotal } from "@/lib/api/types";
import { likelyTotalMessages } from "@/lib/segmentation";

interface Props {
  items: LikelyTotal[] | undefined;
  noun: "bars" | "shares";
}

/** Amber line(s) under a segmentation chart: a segment that equals the sum of
 * the others in some years is probably a provider total row, so the stack is
 * counted twice there. Warning only; no value is hidden or changed. Same
 * `text-xs text-warn` line as FmpRatiosNote. Nothing when there are no flags. */
export function LikelyTotalNote({ items, noun }: Props) {
  const messages = likelyTotalMessages(items ?? [], noun);
  if (messages.length === 0) return null;
  return (
    <div className="space-y-0.5">
      {messages.map((message) => (
        <p key={message} className="text-xs text-warn">
          {message}
        </p>
      ))}
    </div>
  );
}
