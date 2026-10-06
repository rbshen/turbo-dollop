"use client";

// The Settings layout kit -- see "Settings layout" in docs/design-system.md.
//
//   SettingsSection  a titled section: title, an intro capped at max-w-xl,
//                    then a body capped at max-w-2xl
//   SettingsGroup    an optional sub-heading over a run of rows (use one only
//                    when a section has more than four settings)
//   SettingsRow      one setting: label and hint in the flexible left column,
//                    its control LEFT-aligned in a fixed-width control column
//                    on the right, py-3, a hairline between rows, an error
//                    line under the box
//   SettingsFooter   Save, a status message (aria-live), "Last updated"
//
// Rows are rows, not a grid of fields. A control inside a row takes its id,
// aria-describedby, invalid and disabled state from the row (FormField's
// context), so it needs only its own value props.
import { useId, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/ui/section";
import {
  FIELD_ERROR_CLASS,
  FIELD_HINT_CLASS,
  FIELD_LABEL_CLASS,
  FieldProvider,
  useFieldContextValue,
} from "@/components/ui/form-field";
import { cn } from "@/lib/utils";

// The control column: ONE width for every row of every section, so all boxes
// share one left edge whatever a row's unit is. 16rem = 256px = the widest
// field allowed in a row (medium, 176px) + an 80px unit slot (the 8px gap and
// the unit trail into it; a row with no unit leaves it empty). Set here and
// nowhere else; the class is a full literal so Tailwind can see it. Below `sm`
// the grid is one column and the row stacks.
export const SETTINGS_CONTROL_COLUMN_CLASS = "sm:grid-cols-[minmax(0,1fr)_16rem]";

export function SettingsSection({
  title,
  intro,
  children,
  className,
}: {
  title: ReactNode;
  /** What the section controls and when a change takes effect. Plain English. */
  intro?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Section title={title} className={className}>
      {intro && <p className="max-w-xl text-sm text-text-secondary">{intro}</p>}
      <div className="mt-4 max-w-2xl">{children}</div>
    </Section>
  );
}

export function SettingsGroup({
  title,
  children,
  className,
}: {
  /** A sub-heading. Only when the section has more than four settings. */
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const headingId = useId();
  return (
    <div
      role={title ? "group" : undefined}
      aria-labelledby={title ? headingId : undefined}
      className={cn("[&:not(:first-child)]:mt-8", className)}
    >
      {title && (
        <h3 id={headingId} className="pb-2 text-xs font-semibold text-text-secondary">
          {title}
        </h3>
      )}
      <div className="divide-y divide-border-subtle">{children}</div>
    </div>
  );
}

export function SettingsRow({
  label,
  hint,
  htmlFor,
  error,
  disabled,
  children,
  className,
}: {
  label: ReactNode;
  /** One short plain-English sentence, linked to the control by aria-describedby. */
  hint?: ReactNode;
  /** The id of the control in this row; also the label's `for`. */
  htmlFor: string;
  /** An inline error, shown under the control. */
  error?: ReactNode;
  /** Dims the label and hint and disables the control (a conditional row). */
  disabled?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const ctx = useFieldContextValue(htmlFor, { hint, error, disabled });
  return (
    <FieldProvider value={ctx}>
      <div
        className={cn("grid grid-cols-1 items-center gap-x-6 gap-y-2 py-3", SETTINGS_CONTROL_COLUMN_CLASS, className)}
      >
        <div className={cn("flex min-w-0 flex-col gap-0.5", disabled && "opacity-45")}>
          <label htmlFor={htmlFor} className={FIELD_LABEL_CLASS}>
            {label}
          </label>
          {hint && (
            <p id={ctx.hintId} className={FIELD_HINT_CLASS}>
              {hint}
            </p>
          )}
        </div>
        {/* Left-aligned in the control column: box (and checkbox/switch) start
            at the column's left edge; the unit trails into the slot after it. */}
        <div className="flex min-w-0 max-w-full justify-start">{children}</div>
        {error && (
          <p id={ctx.errorId} role="alert" className={cn(FIELD_ERROR_CLASS, "text-left sm:col-start-2")}>
            {error}
          </p>
        )}
      </div>
    </FieldProvider>
  );
}

export type SaveStatus = "idle" | "saving" | "saved" | "error";

const STATUS_TEXT: Record<SaveStatus, string> = {
  idle: "",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function SettingsFooter({
  onSave,
  status,
  updatedAt,
  invalid = false,
  unchanged = false,
  message: errorMessage,
  secondary,
  className,
}: {
  onSave: () => void;
  status: SaveStatus;
  /** ISO timestamp (or Date) of the stored settings; shown as "Last updated ...". */
  updatedAt: string | Date;
  /** A field is invalid: Save is disabled and the status says why. */
  invalid?: boolean;
  /** Nothing differs from the stored values yet: Save is disabled (no message). */
  unchanged?: boolean;
  /** The server's reason for a failed save, shown after "Save failed". */
  message?: string;
  /** A second action beside Save (an outline button such as "Reset to defaults"). Rendered right after Save. */
  secondary?: ReactNode;
  className?: string;
}) {
  const message = invalid
    ? "Fix the highlighted fields to save."
    : status === "error" && errorMessage
      ? `${STATUS_TEXT.error}: ${errorMessage}`
      : STATUS_TEXT[status];
  return (
    <div className={cn("mt-6 flex flex-wrap items-center gap-x-3 gap-y-1", className)}>
      <Button variant="primary" onClick={onSave} disabled={status === "saving" || invalid || unchanged}>
        Save
      </Button>
      {secondary}
      <span
        aria-live="polite"
        className={cn("text-xs", status === "error" && !invalid ? "text-negative" : "text-text-secondary")}
      >
        {message}
      </span>
      <p className="text-xs text-text-tertiary">Last updated {new Date(updatedAt).toLocaleString()}</p>
    </div>
  );
}
