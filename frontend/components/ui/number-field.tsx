"use client";

// NumberField -- a typed number: a text input (inputMode="decimal"), not a
// native type="number". No browser spinner, no scroll-wheel value change, no
// "e" character. ArrowUp/ArrowDown step by `step`, Shift+Arrow by ten times
// that; stepping only acts on a valid value and stops at min/max.
//
// It NEVER clamps, rounds or snaps what was typed. `value` is the raw text
// the parent holds; a value that is not a number, is not whole where
// `integer` is set, or is outside min/max gets the invalid style and an
// inline error under the field, and `onChange` reports the same check as its
// second argument so the parent can gate its Save on it. `min`/`max` are
// optional and should mirror bounds the server already enforces.
//
// `stepper` (off by default) joins 32px -/+ buttons to the field's edges:
// [-][ 30 ][+]. They are outside the token width and skipped by Tab (the
// arrow keys are the keyboard route, as on a native spin button).
//
// Inside a FormField/SettingsRow the field takes its id and description ids
// from the context, and the ROW shows the error when the parent gives it one;
// if the row has none, the field falls back to showing its own message so an
// invalid value is never silent.
import { forwardRef, useId, type InputHTMLAttributes, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { Minus, Plus } from "@phosphor-icons/react";
import {
  FIELD_BOX_CLASS,
  FIELD_INVALID_CLASS,
  FIELD_SIZE_CLASS,
  joinIds,
  type FieldSize,
} from "@/lib/formControl";
import { checkNumber, stepNumber, type NumberCheck } from "@/lib/numberInput";
import { cn } from "@/lib/utils";
import { FIELD_ERROR_CLASS, FIELD_UNIT_CLASS, useFormFieldContext } from "@/components/ui/form-field";

export interface NumberFieldProps
  extends Omit<
    InputHTMLAttributes<HTMLInputElement>,
    "value" | "onChange" | "size" | "type" | "inputMode" | "min" | "max" | "step"
  > {
  /** The raw text. The parent owns it; it is never rewritten for you. */
  value: string;
  /** Called with the new text and its validation result. */
  onChange: (value: string, check: NumberCheck) => void;
  integer?: boolean;
  min?: number;
  max?: number;
  /** Arrow-key and button step. Default 1. */
  step?: number;
  /** A suffix after the box: `[ 30 ] weeks`. */
  unit?: ReactNode;
  size?: FieldSize;
  invalid?: boolean;
  /** An error from outside the field (a cross-field or server message). */
  error?: ReactNode;
  stepper?: boolean;
}

const STEPPER_BUTTON_CLASS =
  "flex h-9 w-8 shrink-0 items-center justify-center border border-border-control bg-page text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-page disabled:hover:text-text-secondary";

export const NumberField = forwardRef<HTMLInputElement, NumberFieldProps>(function NumberField(
  {
    id,
    value,
    onChange,
    integer = false,
    min,
    max,
    step = 1,
    unit,
    size = "short",
    invalid,
    error,
    disabled,
    stepper = false,
    className,
    onKeyDown,
    "aria-describedby": ariaDescribedBy,
    ...rest
  },
  ref,
) {
  const ctx = useFormFieldContext();
  const autoId = useId();
  const fieldId = id ?? ctx?.id ?? autoId;
  const isDisabled = disabled ?? ctx?.disabled ?? false;

  const check = checkNumber(value, { integer, min, max });
  // A disabled field (a conditional row that does not apply) shows no
  // validation of its own; the parent ignores it when saving.
  const message = error ?? (isDisabled ? null : check.error);
  const isInvalid = invalid ?? (Boolean(message) || (ctx?.invalid ?? false));

  const unitId = `${fieldId}-unit`;
  const errorId = `${fieldId}-error`;
  const showOwnError = Boolean(message) && !ctx?.errorId;

  const validNow = !isDisabled && check.value !== null && check.error === null;

  function emit(text: string) {
    onChange(text, checkNumber(text, { integer, min, max }));
  }

  function stepBy(direction: 1 | -1, big: boolean) {
    if (!validNow || check.value === null) return;
    emit(String(stepNumber(check.value, direction, step, big, { min, max })));
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    onKeyDown?.(e);
    if (e.defaultPrevented) return;
    if ((e.key === "e" || e.key === "E") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
    } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      stepBy(e.key === "ArrowUp" ? 1 : -1, e.shiftKey);
    }
  }

  const input = (
    <input
      ref={ref}
      id={fieldId}
      type="text"
      inputMode="decimal"
      autoComplete="off"
      spellCheck={false}
      value={value}
      disabled={isDisabled}
      aria-invalid={isInvalid ? true : undefined}
      aria-describedby={joinIds(
        ariaDescribedBy,
        ctx?.hintId,
        ctx?.unitId,
        unit ? unitId : undefined,
        ctx?.errorId,
        showOwnError ? errorId : undefined,
      )}
      onChange={(e) => emit(e.target.value)}
      onKeyDown={handleKeyDown}
      className={cn(
        FIELD_BOX_CLASS,
        "min-w-0 font-mono tabular-nums",
        FIELD_SIZE_CLASS[size],
        stepper ? "rounded-none text-center" : null,
        isInvalid && FIELD_INVALID_CLASS,
        className,
      )}
      {...rest}
    />
  );

  return (
    <div className={cn("flex max-w-full flex-col gap-1", size === "full" ? "w-full" : "w-fit")}>
      <div className="flex max-w-full items-center gap-2">
        {stepper ? (
          <div className={cn("flex min-w-0 max-w-full items-stretch", size === "full" && "w-full")}>
            <button
              type="button"
              tabIndex={-1}
              aria-label="Decrease"
              className={cn(STEPPER_BUTTON_CLASS, "rounded-l-md border-r-0")}
              disabled={!validNow || (min !== undefined && check.value !== null && check.value <= min)}
              onClick={(e: MouseEvent) => stepBy(-1, e.shiftKey)}
            >
              <Minus size={12} weight="bold" />
            </button>
            {input}
            <button
              type="button"
              tabIndex={-1}
              aria-label="Increase"
              className={cn(STEPPER_BUTTON_CLASS, "rounded-r-md border-l-0")}
              disabled={!validNow || (max !== undefined && check.value !== null && check.value >= max)}
              onClick={(e: MouseEvent) => stepBy(1, e.shiftKey)}
            >
              <Plus size={12} weight="bold" />
            </button>
          </div>
        ) : (
          input
        )}
        {unit && (
          <span id={unitId} className={FIELD_UNIT_CLASS}>
            {unit}
          </span>
        )}
      </div>
      {showOwnError && (
        <p id={errorId} role="alert" className={FIELD_ERROR_CLASS}>
          {message}
        </p>
      )}
    </div>
  );
});
