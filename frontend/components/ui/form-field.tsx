"use client";

// FormField -- the anatomy of one form control: a real <label>, an optional
// one-sentence hint directly under it, the control (with an optional unit
// suffix, `[ 30 ] weeks`) and an inline error under the field. The hint, the
// unit and the error are wired to the control with aria-describedby through
// a small context, so a control inside a FormField (or a SettingsRow) needs
// only its own value props: NumberField, Input, Select, Checkbox and Switch
// read the id, description ids, invalid and disabled state from it, and any
// prop passed to the control itself still wins. Outside a FormField the
// context is null and those controls behave exactly as they always have.
import { createContext, useContext, useMemo, type HTMLAttributes, type ReactNode } from "react";
import { joinIds } from "@/lib/formControl";
import { cn } from "@/lib/utils";

export interface FormFieldContextValue {
  /** The control's id (the label's htmlFor). */
  id: string;
  hintId?: string;
  unitId?: string;
  /** Set only while the enclosing field is showing an error message. */
  errorId?: string;
  invalid: boolean;
  disabled: boolean;
}

const FormFieldContext = createContext<FormFieldContextValue | null>(null);

export function useFormFieldContext(): FormFieldContextValue | null {
  return useContext(FormFieldContext);
}

/** hint + unit + error ids of the enclosing field, for aria-describedby. */
export function describedByOf(ctx: FormFieldContextValue | null): string | undefined {
  return ctx ? joinIds(ctx.hintId, ctx.unitId, ctx.errorId) : undefined;
}

export function useFieldContextValue(
  id: string,
  { hint, unit, error, disabled }: { hint?: ReactNode; unit?: ReactNode; error?: ReactNode; disabled?: boolean },
): FormFieldContextValue {
  const hasHint = Boolean(hint);
  const hasUnit = Boolean(unit);
  const hasError = Boolean(error);
  const isDisabled = Boolean(disabled);
  return useMemo(
    () => ({
      id,
      hintId: hasHint ? `${id}-hint` : undefined,
      unitId: hasUnit ? `${id}-unit` : undefined,
      errorId: hasError ? `${id}-error` : undefined,
      invalid: hasError,
      disabled: isDisabled,
    }),
    [id, hasHint, hasUnit, hasError, isDisabled],
  );
}

export const FIELD_LABEL_CLASS = "text-sm text-text-primary";
export const FIELD_HINT_CLASS = "text-xs text-text-tertiary";
export const FIELD_UNIT_CLASS = "whitespace-nowrap text-sm text-text-secondary";
export const FIELD_ERROR_CLASS = "text-xs text-negative";

export function FieldProvider({ value, children }: { value: FormFieldContextValue; children: ReactNode }) {
  return <FormFieldContext.Provider value={value}>{children}</FormFieldContext.Provider>;
}

export interface FormFieldProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  label: ReactNode;
  /** The id of the control inside; also the label's `for`. */
  htmlFor: string;
  /** One short plain-English sentence, shown under the label. */
  hint?: ReactNode;
  /** A suffix after the control: `[ 30 ] weeks`. Labels drop the unit. For a
   * NumberField use its own `unit` prop instead (it also sits after the box). */
  unit?: ReactNode;
  /** An inline error under the field; the control gets the invalid style. */
  error?: ReactNode;
  disabled?: boolean;
  children: ReactNode;
}

export function FormField({ label, htmlFor, hint, unit, error, disabled, children, className, ...props }: FormFieldProps) {
  const ctx = useFieldContextValue(htmlFor, { hint, unit, error, disabled });
  return (
    <FieldProvider value={ctx}>
      <div className={cn("flex flex-col gap-1", className)} {...props}>
        <label htmlFor={htmlFor} className={cn(FIELD_LABEL_CLASS, disabled && "opacity-45")}>
          {label}
        </label>
        {hint && (
          <p id={ctx.hintId} className={cn(FIELD_HINT_CLASS, disabled && "opacity-45")}>
            {hint}
          </p>
        )}
        <div className="mt-0.5 flex max-w-full items-center gap-2">
          {children}
          {unit && (
            <span id={ctx.unitId} className={FIELD_UNIT_CLASS}>
              {unit}
            </span>
          )}
        </div>
        {error && (
          <p id={ctx.errorId} role="alert" className={FIELD_ERROR_CLASS}>
            {error}
          </p>
        )}
      </div>
    </FieldProvider>
  );
}
