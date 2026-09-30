"use client";

// The Settings layout kit -- see "Settings layout" in docs/design-system.md.
//
//   SettingsSection  a titled section: title, an intro capped at max-w-xl,
//                    then a body capped at max-w-2xl
//   SettingsGroup    an optional sub-heading over a run of rows (use one only
//                    when a section has more than four settings)
//   SettingsRow      one setting: label and hint on the left, its control on
//                    the right (grid-cols-[1fr_auto]), py-3, a hairline
//                    between rows, an error line under the control
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
        className={cn(
          "grid grid-cols-[1fr_auto] items-center gap-x-6 gap-y-1 py-3 max-sm:grid-cols-1",
          className,
        )}
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
        <div className="flex max-w-full justify-self-start sm:justify-self-end">{children}</div>
        {error && (
          <p
            id={ctx.errorId}
            role="alert"
            className={cn(FIELD_ERROR_CLASS, "col-span-full max-w-md justify-self-start text-left sm:justify-self-end sm:text-right")}
          >
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
  className,
}: {
  onSave: () => void;
  status: SaveStatus;
  /** ISO timestamp (or Date) of the stored settings; shown as "Last updated ...". */
  updatedAt: string | Date;
  /** A field is invalid: Save is disabled and the status says why. */
  invalid?: boolean;
  className?: string;
}) {
  const message = invalid ? "Fix the highlighted fields to save." : STATUS_TEXT[status];
  return (
    <div className={cn("mt-6 flex flex-wrap items-center gap-x-3 gap-y-1", className)}>
      <Button variant="primary" onClick={onSave} disabled={status === "saving" || invalid}>
        Save
      </Button>
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
