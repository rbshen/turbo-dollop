"use client";

import { Tabs, type TabItem } from "@/components/ui/tabs";
import { TICKER_TABS, type TickerTab } from "@/lib/tickerTabs";

interface Props {
  active: TickerTab;
  onChange: (tab: TickerTab) => void;
}

const TAB_ITEMS: TabItem[] = TICKER_TABS.map(({ key, label }) => ({ value: key, label }));

export function TickerTabs({ active, onChange }: Props) {
  return <Tabs value={active} onValueChange={(v) => onChange(v as TickerTab)} items={TAB_ITEMS} />;
}
