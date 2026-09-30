"use client";

// SideNav -- a vertical list of links for moving between areas of one
// section (e.g. Settings). No box, no active-route detection of its own:
// the caller decides which item is current via each item's `current` prop.
import type { ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export interface SideNavItem {
  href: string;
  label: ReactNode;
  current?: boolean;
}

export interface SideNavProps {
  items: SideNavItem[];
  className?: string;
}

export function SideNav({ items, className }: SideNavProps) {
  return (
    <nav className={cn("flex w-58 flex-col gap-0.5", className)}>
      {items.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={item.current ? "page" : undefined}
          className={cn(
            "flex h-9 items-center rounded-md px-3 text-sm font-medium transition-colors",
            item.current ? "bg-surface-2 text-text-primary" : "text-text-secondary hover:text-text-primary",
          )}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
