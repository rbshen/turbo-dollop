"use client";

// Input -- the underline text field used inline (filters, forms), plus a
// `boxed` variant for the one place that needs a visible container (the
// global ticker search). Field wraps either with a caption-style label.
import { forwardRef, type InputHTMLAttributes, type LabelHTMLAttributes, type ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

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

export interface InputProps extends InputHTMLAttributes<HTMLInputElement>, VariantProps<typeof inputVariants> {}

// Every Input must be usable with a visible label (see Field, below) or an
// aria-label -- the underline variant especially gives no other affordance.
export const Input = forwardRef<HTMLInputElement, InputProps>(({ className, variant, type, ...props }, ref) => {
  return (
    <input
      ref={ref}
      type={type}
      className={cn(
        inputVariants({ variant }),
        type === "number" &&
          "font-mono tabular-nums [-moz-appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
        className,
      )}
      {...props}
    />
  );
});
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
