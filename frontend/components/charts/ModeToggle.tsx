import { SegmentedControl } from "@/components/shared/SegmentedControl";

interface Props {
  mode: "bar" | "line";
  onChange: (mode: "bar" | "line") => void;
}

const OPTIONS: { value: "bar" | "line"; label: string }[] = [
  { value: "bar", label: "bar" },
  { value: "line", label: "line" },
];

export function ModeToggle({ mode, onChange }: Props) {
  return <SegmentedControl value={mode} onChange={onChange} options={OPTIONS} />;
}
