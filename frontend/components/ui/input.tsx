"use client";

// Input -- the underline text field used inline (filters), plus a `boxed`
// variant (the ticker search and, per docs/design-system.md "Form controls",
// every form page). Field wraps either with a caption-style label.
//
// Opt-in additions (session 8; nothing changes unless a prop is passed):
//   size    -- a width token (short/medium/wide/full) that also makes the
//              field 36px high. Replaces the native `size` attribute, which
//              no call site used.
//   invalid -- the invalid border colour and aria-invalid; pair it with an
//              error message (FormField renders one).
// Inside a FormField/SettingsRow it also picks up id, aria-describedby,
// invalid and disabled from the field; a prop passed here still wins.
import { forwardRef, type InputHTMLAttributes, type LabelHTMLAttributes, type ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { FIELD_INVALID_CLASS, FIELD_SIZE_CLASS, type FieldSize } from "@/lib/formControl";
import { cn } from "@/lib/utils";
import { describedByOf, useFormFieldContext } from "@/components/ui/form-field";

const inputVariants = cva(
  "text-sm text-text-primary placeholder:text-text-tertiary bg-transparent transition-colors disabled:cursor-not-allowed disabled:opacity-45",
  {
    variants: {
      variant: {
        underline: "h-8 rounded-none border-0 border-b border-border-control px-0.5",
        boxed: "h-9 rounded-md border border-border-control bg-page px-3",
      },
    },
    defaultVariants: {
      variant: "underline",
    },
  },
);

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size">, VariantProps<typeof inputVariants> {
  size?: FieldSize;
  invalid?: boolean;
}

// Every Input must be usable with a visible label (see Field, below) or an
// aria-label -- the underline variant especially gives no other affordance.
export const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    { className, variant, type, size, invalid, id, disabled, "aria-describedby": ariaDescribedBy, "aria-invalid": ariaInvalid, ...props },
    ref,
  ) => {
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
          inputVariants({ variant }),
          type === "number" &&
            "font-mono tabular-nums [-moz-appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
          size && ["h-9", FIELD_SIZE_CLASS[size]],
          isInvalid && FIELD_INVALID_CLASS,
          className,
        )}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export interface FieldProps extends LabelHTMLAttributes<HTMLLabelElement> {
  label: ReactNode;
  htmlFor: string;
  applied?: boolean;
  children: ReactNode;
}

// `applied` colors the label with the filter-active orange -- the one
// documented exception to the single-accent rule, for a filter field that
// currently holds a non-default value.
export function Field({ label, htmlFor, applied, children, className, ...props }: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <label
        htmlFor={htmlFor}
        className={cn("text-xs", applied ? "text-filter-active" : "text-text-tertiary")}
        {...props}
      >
        {label}
      </label>
      {children}
    </div>
  );
}
