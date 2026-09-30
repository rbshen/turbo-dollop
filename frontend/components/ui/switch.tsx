"use client";

// Switch -- an on/off setting that applies the moment it is flipped (use a
// Checkbox for a setting saved with a Save button). A hidden native
// <input type="checkbox" role="switch"> drives a 32x18 track and a 12px
// thumb via `peer`, the same technique and the same focus ring as Checkbox,
// so keyboard (Space), click and label semantics come from the browser.
// On is neutral (text-primary track, dark thumb), never brand blue.
import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { describedByOf, useFormFieldContext } from "@/components/ui/form-field";

export interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "role" | "size"> {
  /** Omit when the switch sits in a SettingsRow, whose label names it. */
  label?: ReactNode;
}

export const Switch = forwardRef<HTMLInputElement, SwitchProps>(
  ({ className, label, id, disabled, "aria-describedby": ariaDescribedBy, ...props }, ref) => {
    const ctx = useFormFieldContext();
    const fieldId = id ?? ctx?.id;
    return (
      <label
        htmlFor={fieldId}
        className={cn(
          "inline-flex items-center gap-2 text-sm text-text-primary",
          "has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-45",
          "has-[:not(:disabled)]:cursor-pointer",
          className,
        )}
      >
        <span className="relative inline-flex h-[18px] w-8 shrink-0">
          <input
            ref={ref}
            id={fieldId}
            type="checkbox"
            role="switch"
            disabled={disabled ?? ctx?.disabled}
            aria-describedby={ariaDescribedBy ?? describedByOf(ctx)}
            className="peer sr-only"
            {...props}
          />
          <span
            aria-hidden
            className="absolute inset-0 rounded-full border border-border-control bg-surface-2 transition-colors peer-checked:border-text-primary peer-checked:bg-text-primary peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand"
          />
          <span
            aria-hidden
            className="absolute left-[3px] top-[3px] h-3 w-3 rounded-full bg-text-secondary transition-transform peer-checked:translate-x-3.5 peer-checked:bg-page"
          />
        </span>
        {label && <span>{label}</span>}
      </label>
    );
  },
);
Switch.displayName = "Switch";
