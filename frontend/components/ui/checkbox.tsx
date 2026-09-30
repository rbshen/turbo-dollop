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
// `variant` (session 8, opt-in): the default "brand" paints checked in brand
// blue exactly as before. "neutral" is the design-system checked state
// (Principle 3): text-primary fill with a dark check. "chip" is neutral plus
// the Screener toggle-chip shell done properly -- a 32px radius-md chip with a
// border-input hairline that fills surface-2 when checked. At migration
// "neutral" becomes the default and "brand" goes away.
import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { Check } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { describedByOf, useFormFieldContext } from "@/components/ui/form-field";

export interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
  variant?: "brand" | "neutral" | "chip";
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, id, variant = "brand", disabled, "aria-describedby": ariaDescribedBy, ...props }, ref) => {
    const ctx = useFormFieldContext();
    const fieldId = id ?? ctx?.id;
    const neutral = variant !== "brand";
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
        <span className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center">
          <input
            ref={ref}
            id={fieldId}
            type="checkbox"
            disabled={disabled ?? ctx?.disabled}
            aria-describedby={ariaDescribedBy ?? describedByOf(ctx)}
            className="peer sr-only"
            {...props}
          />
          <span
            aria-hidden
            className={cn(
              "absolute inset-0 rounded-[3px] border border-border-control transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand",
              neutral
                ? "peer-checked:border-text-primary peer-checked:bg-text-primary"
                : "peer-checked:border-brand peer-checked:bg-brand",
            )}
          />
          <Check
            aria-hidden
            weight="bold"
            size={11}
            className={cn(
              "relative z-10 opacity-0 peer-checked:opacity-100",
              neutral ? "text-page" : "text-on-brand",
            )}
          />
        </span>
        {label && <span>{label}</span>}
      </label>
    );
  },
);
Checkbox.displayName = "Checkbox";
