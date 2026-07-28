export interface SegmentedControlOption<T extends string> {
  value: T;
  label: string;
}

interface Props<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedControlOption<T>[];
}

// Shared pill-shaped button-group -- ModeToggle (chart bar/line switch),
// FinancialsTab (Annual/Quarterly), and RatingHistoryChart (3-way series
// picker) used to hand-roll this identical markup independently.
export function SegmentedControl<T extends string>({ value, onChange, options }: Props<T>) {
  return (
    <div className="inline-flex flex-wrap overflow-hidden rounded-md border border-zinc-700 text-xs">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={`px-2.5 py-1 capitalize transition-colors ${
            value === option.value ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
