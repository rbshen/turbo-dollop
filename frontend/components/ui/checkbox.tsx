"use client";

// Checkbox -- a native <input type="checkbox">, visually hidden and driven
// via `peer`/`has-*` selectors rather than @base-ui/react's Checkbox
// primitive. Base UI's Checkbox is a headless span+hidden-input pair wired
// through its own Field/Label context (id generation, field groups,
// validation) -- correct label association and state styling depend on
// wiring into that system, which can't be visually confirmed without a
// browser in this session. A native input gives guaranteed keyboard/click/
// label semantics for free and needs no such verification.
//
// The checked state is neutral (design-system Principle 3): text-primary fill
// with a dark check, never brand blue. `variant` is "neutral" (the default) or
// "chip": neutral plus the Screener toggle-chip shell -- a 32px radius-md chip
// with a border-input hairline that fills surface-2 when checked (the checked
// fill is what says "applied"; give it className="w-full" in the sidebar).
//
// With no `label` prop (a Settings row, whose own <label for> names it) there
// is no wrapping <label> at all: the input is laid over the box, so a click on
// the box still toggles it, and the row's label is the only accessible name.
import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { Check } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { describedByOf, useFormFieldContext } from "@/components/ui/form-field";

export interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
  variant?: "neutral" | "chip";
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, id, variant = "neutral", disabled, "aria-describedby": ariaDescribedBy, ...props }, ref) => {
    const ctx = useFormFieldContext();
    const fieldId = id ?? ctx?.id;
    // A label-less checkbox is not wrapped in a <label>: the input covers the box.
    const bare = !label && variant !== "chip";
    const control = (
      <span
        className={cn(
          "relative inline-flex h-4 w-4 shrink-0 items-center justify-center",
          bare && ["has-[:disabled]:opacity-45", className],
        )}
      >
        <input
          ref={ref}
          id={fieldId}
          type="checkbox"
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
            "absolute inset-0 rounded-[3px] border border-border-control transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand",
            "peer-checked:border-text-primary peer-checked:bg-text-primary",
            bare && "pointer-events-none",
          )}
        />
        <Check
          aria-hidden
          weight="bold"
          size={11}
          className={cn(
            "relative z-10 text-page opacity-0 peer-checked:opacity-100",
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
          variant === "chip" &&
            "h-8 rounded-md border border-border-input px-2 text-xs font-medium text-text-secondary transition-colors has-[:checked]:bg-surface-2 has-[:checked]:text-text-primary",
          className,
        )}
      >
        {control}
        {label && <span>{label}</span>}
      </label>
    );
  },
);
Checkbox.displayName = "Checkbox";
