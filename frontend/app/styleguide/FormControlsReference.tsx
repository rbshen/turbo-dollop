"use client";

// Styleguide reference for the form-control family (session 8). Mock data
// only, no API calls; every control is live so it can be tabbed into and
// typed in. See "Form controls" in docs/design-system.md.
import { useState, type ReactNode } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NumberField, type NumberFieldProps } from "@/components/ui/number-field";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/switch";
import { FIELD_SIZES, type FieldSize } from "@/lib/formControl";
import { checkNumber } from "@/lib/numberInput";

// The outline the keyboard focus ring draws (globals.css *:focus-visible),
// applied by hand so the "focused" column can be shown without a keypress.
const SIMULATED_FOCUS = "outline outline-2 outline-offset-2 outline-brand";

const SIZE_PX: Record<FieldSize, string> = { short: "96px", medium: "176px", wide: "320px", full: "fills container" };

function Caption({ children }: { children: ReactNode }) {
  return <p className="mb-2 text-xs text-text-tertiary">{children}</p>;
}

function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <span className="text-xs text-text-tertiary">{label}</span>
      {children}
    </div>
  );
}

// A controlled NumberField with its own state, for demos.
function DemoNumber({ initial, ...props }: { initial: string } & Partial<Omit<NumberFieldProps, "value" | "onChange">>) {
  const [value, setValue] = useState(initial);
  return <NumberField aria-label={props["aria-label"] ?? "Number"} value={value} onChange={setValue} {...props} />;
}

const STATES = ["Default", "Focused (simulated)", "Filled", "Invalid, with error", "Disabled"];

function StatesRow({ name, cells }: { name: string; cells: ReactNode[] }) {
  return (
    <div>
      <h3 className="mb-3 text-xs font-semibold text-text-secondary">{name}</h3>
      <div className="grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-5">
        {cells.map((cell, i) => (
          <Cell key={STATES[i]} label={STATES[i]}>
            {cell}
          </Cell>
        ))}
      </div>
    </div>
  );
}

export function FormControlsReference() {
  return (
    <div className="flex flex-col gap-12">
      <div>
        <Caption>
          Every control in every state. All are 36px high; the invalid state is a red border plus an error line
          under the field. Focus is the global 2px brand outline, drawn here by hand in the second column; tab into
          any live control below to see the real one.
        </Caption>
        <div className="flex flex-col gap-8">
          <StatesRow
            name="NumberField"
            cells={[
              <DemoNumber key="a" initial="" aria-label="Default number" />,
              <DemoNumber key="b" initial="30" aria-label="Focused number" className={SIMULATED_FOCUS} />,
              <DemoNumber key="c" initial="30" aria-label="Filled number" unit="weeks" />,
              <DemoNumber key="d" initial="1" aria-label="Invalid number" integer min={2} max={200} unit="weeks" />,
              <DemoNumber key="e" initial="30" aria-label="Disabled number" disabled unit="weeks" />,
            ]}
          />
          <StatesRow
            name="Input"
            cells={[
              <Input key="a" size="short" placeholder="SPY" aria-label="Default boxed" />,
              <Input key="b" size="short" defaultValue="SPY" aria-label="Focused boxed" className={SIMULATED_FOCUS} />,
              <Input key="c" size="short" defaultValue="SPY" aria-label="Filled boxed" />,
              <FormField key="d" label="Benchmark" htmlFor="sg-boxed-invalid" error="Enter a ticker symbol.">
                <Input id="sg-boxed-invalid" size="short" defaultValue="" />
              </FormField>,
              <Input key="e" size="short" defaultValue="SPY" disabled aria-label="Disabled boxed" />,
            ]}
          />
          <StatesRow
            name="Select (native)"
            cells={[
              <Select key="a" size="short" aria-label="Default select" defaultValue="">
                <option value="" disabled>
                  Choose
                </option>
                <option>EMA</option>
                <option>SMA</option>
              </Select>,
              <Select key="b" size="short" aria-label="Focused select" defaultValue="EMA" className={SIMULATED_FOCUS}>
                <option>EMA</option>
                <option>SMA</option>
              </Select>,
              <Select key="c" size="short" aria-label="Filled select" defaultValue="SMA">
                <option>EMA</option>
                <option>SMA</option>
              </Select>,
              <FormField key="d" label="MA type" htmlFor="sg-select-invalid" error="Choose a type.">
                <Select id="sg-select-invalid" size="short" defaultValue="">
                  <option value="" disabled>
                    Choose
                  </option>
                  <option>EMA</option>
                </Select>
              </FormField>,
              <Select key="e" size="short" aria-label="Disabled select" defaultValue="EMA" disabled>
                <option>EMA</option>
              </Select>,
            ]}
          />
        </div>
      </div>

      <div>
        <Caption>
          Size tokens: short 96px, medium 176px, wide 320px, full fills the container. Height is always 36px and width
          is capped at the container, so a wide field in a narrow container shrinks instead of overflowing (the dashed
          box below is 160px).
        </Caption>
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
          <div className="flex flex-col gap-3">
            <h3 className="text-xs font-semibold text-text-secondary">NumberField</h3>
            {FIELD_SIZES.map((size) => (
              <Cell key={size} label={`${size} · ${SIZE_PX[size]}`}>
                <DemoNumber initial="30" size={size} aria-label={`NumberField ${size}`} />
              </Cell>
            ))}
          </div>
          <div className="flex flex-col gap-3">
            <h3 className="text-xs font-semibold text-text-secondary">Input</h3>
            {FIELD_SIZES.map((size) => (
              <Cell key={size} label={`${size} · ${SIZE_PX[size]}`}>
                <Input size={size} defaultValue="SPY" aria-label={`Input ${size}`} />
              </Cell>
            ))}
          </div>
          <div className="flex flex-col gap-3">
            <h3 className="text-xs font-semibold text-text-secondary">Select</h3>
            {FIELD_SIZES.map((size) => (
              <Cell key={size} label={`${size} · ${SIZE_PX[size]}`}>
                <Select size={size} aria-label={`Select ${size}`} defaultValue="EMA">
                  <option>EMA</option>
                  <option>SMA</option>
                </Select>
              </Cell>
            ))}
          </div>
        </div>
        <div className="mt-6 w-40 border border-dashed border-border-input p-2">
          <Cell label="wide in a 160px container">
            <DemoNumber initial="30" size="wide" aria-label="Capped wide" />
          </Cell>
        </div>
      </div>

      <div>
        <Caption>
          NumberField with the optional stepper: [-][ 30 ][+], 32px buttons joined to the field&apos;s edges. Off by
          default. ArrowUp/ArrowDown step, Shift steps by 10, and a button disables at its bound. Try typing a
          letter, an e, or a value outside 2 to 52.
        </Caption>
        <div className="grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
          <Cell label="short, min 2 max 52">
            <DemoNumber stepper initial="30" integer min={2} max={52} aria-label="Stepper short" />
          </Cell>
          <Cell label="medium, unit">
            <DemoNumber stepper initial="5" size="medium" integer min={1} max={52} unit="bars" aria-label="Stepper medium" />
          </Cell>
          <Cell label="at its max">
            <DemoNumber stepper initial="52" integer min={2} max={52} aria-label="Stepper at max" />
          </Cell>
          <Cell label="invalid">
            <DemoNumber stepper initial="99" integer min={2} max={52} aria-label="Stepper invalid" />
          </Cell>
          <Cell label="disabled">
            <DemoNumber stepper initial="30" disabled aria-label="Stepper disabled" />
          </Cell>
          <Cell label="typed only (no stepper)">
            <DemoNumber initial="30" integer min={2} max={52} aria-label="Typed only" />
          </Cell>
        </div>
      </div>

      <BoxedFields />
      <ChoiceControls />
      <AnatomyExamples />
    </div>
  );
}

function BoxedFields() {
  return (
    <div>
      <Caption>
        Form fields are boxed: radius-md, 1px border-control, page fill, 36px high. There is no underline variant any
        more (the Screener sidebar, its last user, is boxed too; see docs/decisions.md, session 10).
      </Caption>
      <div className="grid max-w-sm grid-cols-1 gap-y-4">
        <FormField label="Ticker" htmlFor="sg-boxed-ticker">
          <Input id="sg-boxed-ticker" size="medium" defaultValue="AAPL" />
        </FormField>
        <FormField label="Minimum score" htmlFor="sg-boxed-min" hint="Tickers below this score are hidden.">
          <Input id="sg-boxed-min" size="short" type="number" defaultValue={70} />
        </FormField>
        <FormField label="Benchmark" htmlFor="sg-boxed-bad" error="Enter a ticker symbol.">
          <Input id="sg-boxed-bad" size="medium" defaultValue="" />
        </FormField>
        <FormField label="Disabled" htmlFor="sg-boxed-dis">
          <Input id="sg-boxed-dis" size="medium" defaultValue="AAPL" disabled />
        </FormField>
      </div>
    </div>
  );
}

function ChoiceControls() {
  return (
    <div className="flex flex-col gap-8">
      <div>
        <Caption>
          Checkbox. The neutral checked state (text-primary fill, dark check) is the only one; there is no brand
          variant. The chip is the Screener&apos;s toggle chip built as a variant: its checked fill (surface-2) is the
          applied signal, not orange.
        </Caption>
        <div className="grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-2">
          <div className="flex flex-col gap-3">
            <h3 className="text-xs font-semibold text-text-secondary">Checkbox</h3>
            <Checkbox id="sg-n-1" variant="neutral" label="Keep last breached support" />
            <Checkbox id="sg-n-2" variant="neutral" label="Keep last breached support" defaultChecked />
            <Checkbox id="sg-n-3" variant="neutral" label="Disabled" disabled />
            <Checkbox id="sg-n-4" variant="neutral" label="Disabled, checked" disabled defaultChecked />
          </div>
          <div className="flex flex-col items-start gap-3">
            <h3 className="text-xs font-semibold text-text-secondary">Chip</h3>
            <Checkbox id="sg-c-1" variant="chip" label="Speculative growth" />
            <Checkbox id="sg-c-2" variant="chip" label="Speculative growth" defaultChecked />
            <Checkbox id="sg-c-3" variant="chip" label="Speculative growth" disabled />
            <Checkbox id="sg-c-4" variant="chip" label="BB + RSI entry (2h)" defaultChecked />
          </div>
        </div>
      </div>

      <div>
        <Caption>
          Switch, for a setting that applies the moment it is flipped. A 32 by 18px track, neutral when on. Use a
          Checkbox instead on any form that has a Save button.
        </Caption>
        <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
          <Switch id="sg-s-1" label="Off" />
          <Switch id="sg-s-2" label="On" defaultChecked />
          <Switch id="sg-s-3" label="Disabled" disabled />
          <Switch id="sg-s-4" label="Disabled, on" disabled defaultChecked />
          <Switch id="sg-s-5" aria-label="Unlabelled switch, on" defaultChecked />
        </div>
      </div>

      <div>
        <Caption>Native select in the themed shell, at short and medium, with the same height and border as a boxed field.</Caption>
        <div className="flex flex-wrap items-start gap-x-8 gap-y-5">
          <FormField label="MA type" htmlFor="sg-sel-short">
            <Select id="sg-sel-short" size="short" defaultValue="EMA">
              <option>EMA</option>
              <option>SMA</option>
            </Select>
          </FormField>
          <FormField label="When over the cap, keep" htmlFor="sg-sel-medium">
            <Select id="sg-sel-medium" size="medium" defaultValue="nearest_price">
              <option value="nearest_price">Nearest to price</option>
              <option value="most_recent">Most recent</option>
            </Select>
          </FormField>
        </div>
      </div>
    </div>
  );
}

function AnatomyExamples() {
  const [weeks, setWeeks] = useState("30");
  const [bad, setBad] = useState("0");
  return (
    <div>
      <Caption>
        Anatomy, top to bottom: label (unit dropped), a one-sentence hint, the field with its unit as a suffix, then
        the error. The hint, unit and error are wired to the field with aria-describedby; the error is announced.
      </Caption>
      <div className="grid grid-cols-1 gap-x-16 gap-y-8 md:grid-cols-2">
        <FormField label="MA length" htmlFor="sg-an-1" hint="How many weeks the average looks back. Longer reacts more slowly.">
          <NumberField value={weeks} onChange={setWeeks} integer min={2} max={200} unit="weeks" />
        </FormField>
        <FormField
          label="Slope lookback"
          htmlFor="sg-an-2"
          hint="How many weeks back the average is compared with to tell if it is rising or falling."
          error={checkNumber(bad, { integer: true, min: 1, max: 52 }).error ?? undefined}
        >
          <NumberField value={bad} onChange={setBad} integer min={1} max={52} unit="weeks" />
        </FormField>
        <FormField label="RS benchmark" htmlFor="sg-an-3" hint="The ticker each stock's strength is measured against.">
          <Input size="medium" defaultValue="SPY" />
        </FormField>
        <FormField label="Label only" htmlFor="sg-an-4">
          <Input size="medium" defaultValue="No hint, no unit" />
        </FormField>
        <FormField label="Text with a unit suffix" htmlFor="sg-an-5" unit="weeks" hint="A FormField unit works on any control.">
          <Input size="short" defaultValue="30" />
        </FormField>
      </div>
    </div>
  );
}
