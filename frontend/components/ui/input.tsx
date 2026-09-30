"use client";

// Input -- the boxed text field: 36px high, radius-md, 1px border-control, page
// fill (FIELD_BOX_CLASS; the ticker search, the Watchlist name editor, the
// Settings forms and, per docs/design-system.md "Form controls", every form
// page). There is no underline variant any more (session 10: the Screener
// sidebar was its last user).
//
//   size    -- a width token (short/medium/wide/full); every field is 36px high.
//   invalid -- the invalid border colour and aria-invalid; pair it with an
//              error message (FormField renders one).
// Inside a FormField/SettingsRow it also picks up id, aria-describedby,
// invalid and disabled from the field; a prop passed here still wins. Every
// Input needs a visible label (FormField) or an aria-label.
import { forwardRef, type InputHTMLAttributes } from "react";
import { FIELD_BOX_CLASS, FIELD_INVALID_CLASS, FIELD_SIZE_CLASS, type FieldSize } from "@/lib/formControl";
import { cn } from "@/lib/utils";
import { describedByOf, useFormFieldContext } from "@/components/ui/form-field";

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  size?: FieldSize;
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, size, invalid, id, disabled, "aria-describedby": ariaDescribedBy, "aria-invalid": ariaInvalid, ...props }, ref) => {
    const ctx = useFormFieldContext();
    const isInvalid = invalid ?? ctx?.invalid ?? false;
    return (
      <input
        ref={ref}
        type={type}
        id={id ?? ctx?.id}
        disabled={disabled ?? ctx?.disabled}
        aria-invalid={isInvalid ? true : ariaInvalid}
        aria-describedby={ariaDescribedBy ?? describedByOf(ctx)}
        className={cn(
          FIELD_BOX_CLASS,
          type === "number" &&
            "font-mono tabular-nums [-moz-appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
          size && FIELD_SIZE_CLASS[size],
          isInvalid && FIELD_INVALID_CLASS,
          className,
        )}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";
