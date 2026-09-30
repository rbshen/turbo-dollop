"use client";

import type { SelectHTMLAttributes } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { FIELD_INVALID_CLASS, FIELD_SIZE_CLASS, type FieldSize } from "@/lib/formControl";
import { cn } from "@/lib/utils";
import { describedByOf, useFormFieldContext } from "@/components/ui/form-field";

// A native <select> in a themed, appearance-none shell with an overlaid caret:
// the form-page field -- 36px high, radius-md, 1px border-control, the same box
// as a boxed Input, sized by the same width tokens (short/medium/wide/full),
// with the global focus outline (no focus:outline-none). `size` is required:
// a select's width is a token choice, never left to its content. `invalid` adds
// the invalid border colour and aria-invalid. Inside a FormField/SettingsRow it
// picks up id, aria-describedby, invalid and disabled from the field.
// (The old un-tokened shell was removed once its last caller moved to a token.)
export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  size: FieldSize;
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
    <span className={cn("relative block max-w-full", FIELD_SIZE_CLASS[size])}>
      <select
        {...props}
        id={id ?? ctx?.id}
        disabled={disabled ?? ctx?.disabled}
        aria-invalid={isInvalid ? true : ariaInvalid}
        aria-describedby={ariaDescribedBy ?? describedByOf(ctx)}
        className={cn(
          "h-9 w-full appearance-none rounded-md border border-border-control bg-page pl-3 pr-8 text-sm text-text-primary transition-colors disabled:cursor-not-allowed disabled:opacity-45",
          isInvalid && FIELD_INVALID_CLASS,
          className,
        )}
      >
        {children}
      </select>
      <CaretDown
        size={12}
        weight="bold"
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary"
      />
    </span>
  );
}
