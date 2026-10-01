"use client";

import { Tabs, type TabItem } from "@/components/ui/tabs";
import { TICKER_TABS, type TickerTab, type TickerTabDef } from "@/lib/tickerTabs";

interface Props {
  active: TickerTab;
  onChange: (tab: TickerTab) => void;
  /** The tab set; the stock page's by default (the ETF page passes ETF_TICKER_TABS). */
  tabs?: TickerTabDef[];
}

const toItems = (tabs: TickerTabDef[]): TabItem[] => tabs.map(({ key, label }) => ({ value: key, label }));
const STOCK_TAB_ITEMS = toItems(TICKER_TABS);

export function TickerTabs({ active, onChange, tabs }: Props) {
  return <Tabs value={active} onValueChange={(v) => onChange(v as TickerTab)} items={tabs ? toItems(tabs) : STOCK_TAB_ITEMS} />;
}
