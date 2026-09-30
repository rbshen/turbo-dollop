"use client";

// Switch -- an on/off setting that applies the moment it is flipped (use a
// Checkbox for a setting saved with a Save button). A hidden native
// <input type="checkbox" role="switch"> drives a 32x18 track and a 12px
// thumb via `peer`, the same technique and the same focus ring as Checkbox,
// so keyboard (Space), click and label semantics come from the browser.
// On is neutral (text-primary track, dark thumb), never brand blue.
//
// With no `label` prop (a Settings row, whose own <label for> names it) there
// is no wrapping <label>: the input is laid over the track, so a click on the
// track still toggles it and the row's label is the only accessible name.
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
    const bare = !label;
    const control = (
      <span
        className={cn(
          "relative inline-flex h-[18px] w-8 shrink-0",
          bare && ["has-[:disabled]:opacity-45", className],
        )}
      >
        <input
          ref={ref}
          id={fieldId}
          type="checkbox"
          role="switch"
          disabled={disabled ?? ctx?.disabled}
          aria-describedby={ariaDescribedBy ?? describedByOf(ctx)}
          className={
            bare
              ? "peer absolute inset-0 m-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
              : "peer sr-only"
          }
          {...props}
        />
        <span
          aria-hidden
          className={cn(
            "absolute inset-0 rounded-full border border-border-control bg-surface-2 transition-colors peer-checked:border-text-primary peer-checked:bg-text-primary peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand",
            bare && "pointer-events-none",
          )}
        />
        <span
          aria-hidden
          className={cn(
            "absolute left-[3px] top-[3px] h-3 w-3 rounded-full bg-text-secondary transition-transform peer-checked:translate-x-3.5 peer-checked:bg-page",
            bare && "pointer-events-none",
          )}
        />
      </span>
    );
    if (bare) return control;
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
        {control}
        <span>{label}</span>
      </label>
    );
  },
);
Switch.displayName = "Switch";
