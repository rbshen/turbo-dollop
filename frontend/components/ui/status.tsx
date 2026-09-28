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

const TONE_TEXT_CLASS: Record<StatusTone, string> = {
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
}

export function Status({ tone, direction, children, className }: StatusProps) {
  return (
    <span
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
}

export function Verdict({ tone, children, className }: VerdictProps) {
  return <span className={cn("text-xs font-medium", TONE_TEXT_CLASS[tone], className)}>{children}</span>;
}
