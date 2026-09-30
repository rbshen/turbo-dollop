"use client";

// Badge -- the same pill as Status, for a short value or label in a table
// cell or list (a score, a rating, a company kind). Pass `missing` for the
// placeholder "no value" state instead of passing children.
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { pillVariants, type PillSize, type PillTone } from "@/components/ui/pill";

export type BadgeTone = PillTone;

export interface BadgeProps {
  tone?: BadgeTone;
  /** "compact" is for dense tables (Watchlist, Momentum) only. */
  size?: PillSize;
  children?: ReactNode;
  missing?: boolean;
  className?: string;
  /** Native hover tooltip -- same contract as the HTML `title` attribute. */
  title?: string;
}

export function Badge({ tone, size, missing, children, className, title }: BadgeProps) {
  if (missing) {
    return (
      <span title={title} className={cn(pillVariants({ tone: "neutral", size }), "text-text-tertiary", className)}>
        —
      </span>
    );
  }
  return (
    <span title={title} className={cn(pillVariants({ tone, size }), className)}>
      {children}
    </span>
  );
}
