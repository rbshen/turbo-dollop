"use client";

// Tabs -- neutral underline tabs for switching views of the same thing
// (e.g. Summary / Financials / Ratios on a ticker page). Controlled only;
// exactly one tab is ever selected and a tab never triggers an action.
// Built on @base-ui/react's Tabs.Root/List/Tab. TabsPanel is exported for
// callers that want base-ui's own ARIA-linked panel wiring, but it is not
// required -- a caller may just read `value` and render its own content
// anywhere on the page.
import type { ReactNode } from "react";
import { Tabs as TabsPrimitive } from "@base-ui/react/tabs";
import { cn } from "@/lib/utils";

export interface TabItem {
  value: string;
  label: ReactNode;
  /** Optional count shown after the label in the mono figure style. */
  count?: number;
}

export interface TabsProps {
  value: string;
  onValueChange: (value: string) => void;
  items: TabItem[];
  className?: string;
  /** Names the tab list for assistive tech; optional, and absent by default. */
  "aria-label"?: string;
  children?: ReactNode;
}

export function Tabs({ value, onValueChange, items, className, children, "aria-label": ariaLabel }: TabsProps) {
  return (
    <TabsPrimitive.Root value={value} onValueChange={(next) => onValueChange(String(next))}>
      <TabsPrimitive.List aria-label={ariaLabel} className={cn("flex gap-8 overflow-x-auto border-b border-border-subtle", className)}>
        {items.map((item) => (
          <TabsPrimitive.Tab
            key={item.value}
            value={item.value}
            className="-mb-px flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 border-transparent py-3 text-sm font-medium text-text-secondary transition-colors hover:text-text-primary data-[active]:border-text-primary data-[active]:text-text-primary"
          >
            {item.label}
            {item.count != null && <span className="font-mono text-xs tabular-nums text-text-tertiary">{item.count}</span>}
          </TabsPrimitive.Tab>
        ))}
      </TabsPrimitive.List>
      {children}
    </TabsPrimitive.Root>
  );
}

export interface TabsPanelProps {
  value: string;
  children: ReactNode;
  className?: string;
}

export function TabsPanel({ value, children, className }: TabsPanelProps) {
  return (
    <TabsPrimitive.Panel value={value} className={className}>
      {children}
    </TabsPrimitive.Panel>
  );
}
