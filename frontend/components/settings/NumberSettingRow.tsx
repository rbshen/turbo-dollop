"use client";

import { NumberField } from "@/components/ui/number-field";
import { SettingsRow } from "@/components/settings/SettingsLayout";
import type { FieldSize } from "@/lib/formControl";
import { checkNumber, type NumberRules } from "@/lib/numberInput";

// One numeric Settings row. The rules are declared once by the form and used
// for both the field (stepping bounds, own validity) and the row's error, and
// the same rules feed the form's own Save gating. A disabled row (a
// conditional setting that does not apply) is never validated.
export function NumberSettingRow({
  id,
  label,
  hint,
  unit,
  size = "short",
  rules,
  step,
  value,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  hint: string;
  unit?: string;
  size?: FieldSize;
  rules: NumberRules;
  step?: number;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const error = disabled ? null : checkNumber(value, rules).error;
  return (
    <SettingsRow label={label} hint={hint} htmlFor={id} error={error} disabled={disabled}>
      <NumberField value={value} onChange={onChange} size={size} unit={unit} step={step} {...rules} />
    </SettingsRow>
  );
}
