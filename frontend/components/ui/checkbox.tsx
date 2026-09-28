"use client";

// Checkbox -- a native <input type="checkbox">, visually hidden and driven
// via `peer`/`has-*` selectors rather than @base-ui/react's Checkbox
// primitive. Base UI's Checkbox is a headless span+hidden-input pair wired
// through its own Field/Label context (id generation, field groups,
// validation) -- correct label association and state styling depend on
// wiring into that system, which can't be visually confirmed without a
// browser in this session. A native input gives guaranteed keyboard/click/
// label semantics for free and needs no such verification.
import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { Check } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

export interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, id, ...props }, ref) => {
    return (
      <label
        htmlFor={id}
        className={cn(
          "inline-flex items-center gap-2 text-sm text-text-primary",
          "has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-45",
          "has-[:not(:disabled)]:cursor-pointer",
          className,
        )}
      >
        <span className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center">
          <input ref={ref} id={id} type="checkbox" className="peer sr-only" {...props} />
          <span
            aria-hidden
            className="absolute inset-0 rounded-[3px] border border-border-control transition-colors peer-checked:border-brand peer-checked:bg-brand peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand"
          />
          <Check
            aria-hidden
            weight="bold"
            size={11}
            className="relative z-10 text-on-brand opacity-0 peer-checked:opacity-100"
          />
        </span>
        {label && <span>{label}</span>}
      </label>
    );
  },
);
Checkbox.displayName = "Checkbox";
