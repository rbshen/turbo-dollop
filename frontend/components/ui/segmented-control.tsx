"use client";

// SegmentedControl -- switches ONE data option on the current view (e.g.
// index universe, chart range). Built on @base-ui/react's ToggleGroup/
// Toggle. Single-select only: clicking the already-selected segment must
// never deselect it, so ToggleGroup's own multi-select array value is
// wrapped in a single string in/out at this component's boundary and an
// empty commit (the "deselect the only pressed segment" case ToggleGroup
// allows by default) is ignored. Supports 2-6 options; not enforced here.
import type { ReactNode } from "react";
import { Toggle } from "@base-ui/react/toggle";
import { ToggleGroup } from "@base-ui/react/toggle-group";
import { cn } from "@/lib/utils";

export interface SegmentedControlOption {
  value: string;
  label: ReactNode;
}

export interface SegmentedControlProps {
  value: string;
  onValueChange: (value: string) => void;
  options: SegmentedControlOption[];
  className?: string;
}

export function SegmentedControl({ value, onValueChange, options, className }: SegmentedControlProps) {
  return (
    <ToggleGroup
      value={[value]}
      onValueChange={(next) => {
        if (next.length > 0) onValueChange(next[0]);
      }}
      className={cn("inline-flex items-center gap-0.5", className)}
    >
      {options.map((option) => (
        <Toggle
          key={option.value}
          value={option.value}
          className="h-7 shrink-0 rounded-md px-3 text-sm font-medium whitespace-nowrap text-text-secondary transition-colors hover:text-text-primary data-[pressed]:bg-surface-2 data-[pressed]:text-text-primary"
        >
          {option.label}
        </Toggle>
      ))}
    </ToggleGroup>
  );
}
