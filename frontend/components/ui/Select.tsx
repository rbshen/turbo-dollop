"use client";

import type { SelectHTMLAttributes } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

// No shared Select component existed anywhere in the app before this --
// every native <select> (including the Screener's own sort dropdown) is
// bare, with the browser's default arrow. This wraps one in a themed,
// appearance-none shell with an overlaid caret, scoped for reuse wherever
// a dark-themed dropdown is needed next.
export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className="relative block">
      <select
        {...props}
        className={cn(
          "w-full appearance-none rounded border border-zinc-800 bg-zinc-950 py-1.5 pl-2 pr-7 text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none",
          className,
        )}
      >
        {children}
      </select>
      <CaretDown
        size={12}
        weight="bold"
        className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500"
      />
    </span>
  );
}
