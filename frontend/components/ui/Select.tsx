"use client";

import type { SelectHTMLAttributes } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { FIELD_INVALID_CLASS, FIELD_SIZE_CLASS, type FieldSize } from "@/lib/formControl";
import { cn } from "@/lib/utils";
import { describedByOf, useFormFieldContext } from "@/components/ui/form-field";

// No shared Select component existed anywhere in the app before this --
// every native <select> (including the Screener's own sort dropdown) is
// bare, with the browser's default arrow. This wraps one in a themed,
// appearance-none shell with an overlaid caret, scoped for reuse wherever
// a dark-themed dropdown is needed next.
//
// Opt-in restyle (session 8): pass `size` (short/medium/wide/full) and the
// select becomes the form-page field -- 36px high, radius-md, 1px
// border-control, the same box as a boxed Input, sized by the same tokens,
// with the global focus outline (no focus:outline-none). Without `size` it
// renders exactly as before. `invalid` adds the invalid border colour and
// aria-invalid. Inside a FormField/SettingsRow it picks up id,
// aria-describedby, invalid and disabled from the field.
export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  size?: FieldSize;
  invalid?: boolean;
}

export function Select({
  className,
  children,
  size,
  invalid,
  id,
  disabled,
  "aria-describedby": ariaDescribedBy,
  "aria-invalid": ariaInvalid,
  ...props
}: SelectProps) {
  const ctx = useFormFieldContext();
  const isInvalid = invalid ?? ctx?.invalid ?? false;
  return (
    <span className={cn("relative block", size && ["max-w-full", FIELD_SIZE_CLASS[size]])}>
      <select
        {...props}
        id={id ?? ctx?.id}
        disabled={disabled ?? ctx?.disabled}
        aria-invalid={isInvalid ? true : ariaInvalid}
        aria-describedby={ariaDescribedBy ?? describedByOf(ctx)}
        className={cn(
          size
            ? "h-9 w-full appearance-none rounded-md border border-border-control bg-page pl-3 pr-8 text-sm text-text-primary transition-colors disabled:cursor-not-allowed disabled:opacity-45"
            : "w-full appearance-none rounded border border-border-control bg-page py-1.5 pl-2 pr-7 text-sm text-text-primary focus:border-brand focus:outline-none",
          isInvalid && FIELD_INVALID_CLASS,
          className,
        )}
      >
        {children}
      </select>
      <CaretDown
        size={12}
        weight="bold"
        className={cn(
          "pointer-events-none absolute top-1/2 -translate-y-1/2 text-text-tertiary",
          size ? "right-3" : "right-2",
        )}
      />
    </span>
  );
}
