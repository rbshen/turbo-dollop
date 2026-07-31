export interface SegmentedControlOption<T extends string> {
  value: T;
  label: string;
}

interface Props<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedControlOption<T>[];
}

// Shared pill toggle -- separate, individually-rounded buttons with no
// border on an inactive option (a filled brand pill on the active one),
// not a single fused-border bar. Used by FinancialsTab (Annual/Quarterly)
// and EconomicMoatTab (No/Narrow/Wide Moat), which used to hand-roll this
// independently (and briefly diverged in style before being unified here).
export function SegmentedControl<T extends string>({ value, onChange, options }: Props<T>) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium capitalize transition-colors ${
            value === option.value ? "bg-brand text-white" : "text-text-secondary hover:text-text-primary"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
