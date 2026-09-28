"use client";

// Card -- a boxed container. Not the default; reach for Section first.
// Never nested.
import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn("rounded-lg border border-border-card bg-surface p-6", className)}
        {...props}
      />
    );
  },
);
Card.displayName = "Card";
