"use client";

// Button -- primary/ghost/danger actions. `ghost` is the default variant
// (a plain-text action), `primary` is for the one emphasized action in a
// view, `danger` is ghost's negative-tone twin for destructive actions.
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-45",
  {
    variants: {
      variant: {
        primary: "bg-brand text-on-brand hover:bg-brand-hover px-4",
        ghost: "bg-transparent text-text-secondary hover:bg-surface-2 hover:text-text-primary px-3",
        danger: "bg-transparent text-negative hover:bg-negative/10 px-3",
      },
      size: {
        default: "h-9 text-sm",
        sm: "h-7 text-xs",
      },
    },
    defaultVariants: {
      variant: "ghost",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = "button", ...props }, ref) => {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
