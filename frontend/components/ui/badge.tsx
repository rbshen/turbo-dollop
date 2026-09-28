"use client";

// Badge -- a compact filled chip carrying one label. Pass `missing` for the
// placeholder "no value" state instead of passing children.
import type { ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex h-6 items-center justify-center whitespace-nowrap rounded-md px-2 text-xs font-semibold",
  {
    variants: {
      tone: {
        strong: "bg-positive-strong/10 text-positive-strong",
        positive: "bg-positive/10 text-positive",
        warn: "bg-warn/10 text-warn",
        negative: "bg-negative/10 text-negative",
        neutral: "bg-surface-2 text-text-secondary",
      },
    },
    defaultVariants: {
      tone: "neutral",
    },
  },
);

export interface BadgeProps extends VariantProps<typeof badgeVariants> {
  children?: ReactNode;
  missing?: boolean;
  className?: string;
}

export function Badge({ tone, missing, children, className }: BadgeProps) {
  if (missing) {
    return (
      <span className={cn(badgeVariants({ tone: "neutral" }), "bg-surface-2 text-text-tertiary", className)}>
        —
      </span>
    );
  }
  return <span className={cn(badgeVariants({ tone }), className)}>{children}</span>;
}
