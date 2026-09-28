"use client";

// Status -- a labeled state read (a tone dot or up/down glyph plus text),
// never interactive. Verdict is its standalone-word sibling, used beside a
// plain neutral score (e.g. "82  Pass").
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatusTone =
  | "strong"
  | "positive"
  | "warn"
  | "caution"
  | "negative"
  | "speculative"
  | "neutral";

const DOT_CLASS: Record<Exclude<StatusTone, "neutral">, string> = {
  strong: "bg-positive-strong",
  positive: "bg-positive",
  warn: "bg-warn",
  caution: "bg-caution",
  negative: "bg-negative",
  speculative: "bg-chart-purple",
};

// Exported for the rare caller that needs the tone's plain text color
// without either wrapper's own chrome/typography (e.g. ScoreBadge's
// stacked score-number + verdict-word layout, which shares one tone color
// across two differently-sized lines that don't fit Status/Verdict's own
// single-line shape) -- still the one shared source of "what color means
// this tone", never a second hand-rolled copy.
export const TONE_TEXT_CLASS: Record<StatusTone, string> = {
  strong: "text-positive-strong",
  positive: "text-positive",
  warn: "text-warn",
  caution: "text-caution",
  negative: "text-negative",
  speculative: "text-chart-purple",
  neutral: "text-text-secondary",
};

export interface StatusProps {
  tone: StatusTone;
  direction?: "up" | "down";
  children: ReactNode;
  className?: string;
  /** Native hover tooltip -- same contract as the HTML `title` attribute. */
  title?: string;
}

export function Status({ tone, direction, children, className, title }: StatusProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 text-sm",
        tone === "neutral" ? "text-text-secondary" : "text-text-body",
        className,
      )}
    >
      {tone !== "neutral" &&
        (direction ? (
          <span aria-hidden className={cn("text-xs leading-none", TONE_TEXT_CLASS[tone])}>
            {direction === "up" ? "▲" : "▼"}
          </span>
        ) : (
          <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASS[tone])} />
        ))}
      {children}
    </span>
  );
}

export interface VerdictProps {
  tone: StatusTone;
  children: ReactNode;
  className?: string;
  /** Native hover tooltip -- same contract as the HTML `title` attribute. */
  title?: string;
}

export function Verdict({ tone, children, className, title }: VerdictProps) {
  return (
    <span title={title} className={cn("text-xs font-medium", TONE_TEXT_CLASS[tone], className)}>
      {children}
    </span>
  );
}
