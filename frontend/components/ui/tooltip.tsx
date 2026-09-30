"use client";

// Tooltip -- a simple hover/focus popover for a labelled trigger. Built on
// @base-ui/react's Tooltip.Root/Trigger/Portal/Positioner/Popup. Also
// exports TooltipCard, the shared surface look reused by anything that
// needs a "floating card" body (this component and components/ui/chart.tsx's
// chart tooltip).
//
// Hover/focus only: it has no tap-to-toggle, so touch devices (which never
// fire hover) do not get it. The Settings forms' old (i) InfoTooltip, which
// did, was replaced by inline hints and deleted.
import type { ReactNode } from "react";
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";
import { cn } from "@/lib/utils";

export interface TooltipCardProps {
  children: ReactNode;
  className?: string;
}

export function TooltipCard({ children, className }: TooltipCardProps) {
  return (
    <div className={cn("rounded-md border border-border-card bg-surface px-3 py-2 shadow-popover", className)}>
      {children}
    </div>
  );
}

export interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}

// The trigger always renders as a native <button> (Tooltip.Trigger's
// default element) so `children` stays keyboard focusable regardless of
// what's passed -- plain text, an icon, whatever. It isn't meant to wrap
// an already-interactive element (e.g. an existing Button); composing onto
// one would need Trigger's `render` prop, not built here.
export function Tooltip({ content, children, className }: TooltipProps) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger
        delay={150}
        className={cn("inline-flex border-0 bg-transparent p-0 font-inherit text-inherit", className)}
      >
        {children}
      </TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner side="top" sideOffset={6}>
          <TooltipPrimitive.Popup>
            <TooltipCard className="max-w-[280px] text-sm text-text-secondary">{content}</TooltipCard>
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
