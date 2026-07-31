"use client";

import { SegmentedControl } from "@/components/shared/SegmentedControl";
import type { ScreenerUniverse } from "@/lib/api/types";

const UNIVERSE_OPTIONS: { value: ScreenerUniverse; label: string }[] = [
  { value: "sp500", label: "S&P 500" },
  { value: "dow", label: "Dow 30" },
  { value: "all", label: "All" },
];

interface Props {
  value: ScreenerUniverse;
  onChange: (universe: ScreenerUniverse) => void;
}

export function UniverseSelector({ value, onChange }: Props) {
  return <SegmentedControl value={value} onChange={onChange} options={UNIVERSE_OPTIONS} />;
}
