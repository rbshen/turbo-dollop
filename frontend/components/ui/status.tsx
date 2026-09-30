"use client";

// Status -- a labeled state read (a tinted pill, with a ▲/▼ glyph before the
// label when a direction is given), never interactive. Verdict is the same
// pill for a verdict word, used beside a plain neutral score (e.g. "82 [Pass]").
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { pillVariants, type PillSize, type PillTone } from "@/components/ui/pill";

export type StatusTone = PillTone;

export interface StatusProps {
  tone: StatusTone;
  direction?: "up" | "down";
  /** "compact" is for dense tables (Watchlist, Momentum) only. */
  size?: PillSize;
  children: ReactNode;
  className?: string;
  /** Native hover tooltip -- same contract as the HTML `title` attribute. */
  title?: string;
}

export function Status({ tone, direction, size, children, className, title }: StatusProps) {
  return (
    <span title={title} className={cn(pillVariants({ tone, size }), className)}>
      {direction && (
        <span aria-hidden className="text-[0.85em] leading-none">
          {direction === "up" ? "▲" : "▼"}
        </span>
      )}
      {children}
    </span>
  );
}

export interface VerdictProps {
  tone: StatusTone;
  size?: PillSize;
  children: ReactNode;
  className?: string;
  /** Native hover tooltip -- same contract as the HTML `title` attribute. */
  title?: string;
}

export function Verdict({ tone, size, children, className, title }: VerdictProps) {
  return (
    <span title={title} className={cn(pillVariants({ tone, size }), className)}>
      {children}
    </span>
  );
}
