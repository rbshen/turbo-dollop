"use client";

import { CaretDown } from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { AXIS_OPTION_ITEMS } from "@/lib/chartAxis";
import type { AxisOptions } from "@/lib/chartAxis";

interface Props {
  options: AxisOptions;
  onChange: (key: keyof AxisOptions) => void;
}

// The Chart toolbar's "Axis" dropdown: a disclosure button opening a popover with one checkbox per axis readability
// option (lib/chartAxis.ts). Escape or an outside click closes it; Escape returns focus to the button.
export function ChartAxisMenu({ options, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const activeCount = AXIS_OPTION_ITEMS.filter((item) => options[item.key]).length;

  useEffect(() => {
    if (!open) return;
    function onMouseDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open]);

  return (
    <div
      ref={rootRef}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          setOpen(false);
          triggerRef.current?.focus();
        }
      }}
    >
      <Button
        ref={triggerRef}
        variant="outline"
        size="sm"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className="gap-1.5 hover:border-border-input"
      >
        {activeCount > 0 ? `Axis (${activeCount})` : "Axis"}
        <CaretDown size={12} weight="bold" aria-hidden="true" className="text-text-tertiary" />
      </Button>
      {open && (
        <div
          id={panelId}
          role="group"
          aria-label="Axis options"
          className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-border-input bg-surface p-1 shadow-lg"
        >
          {AXIS_OPTION_ITEMS.map((item) => (
            <Checkbox
              key={item.key}
              label={item.label}
              checked={options[item.key]}
              onChange={() => onChange(item.key)}
              className="w-full rounded px-2 py-1.5 text-xs text-text-secondary hover:bg-surface-2"
            />
          ))}
        </div>
      )}
    </div>
  );
}
