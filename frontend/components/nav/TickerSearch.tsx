"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function TickerSearch() {
  const router = useRouter();
  const [value, setValue] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const symbol = value.trim().toUpperCase();
    if (!symbol) return;
    router.push(`/tickers/${symbol}`);
    setValue("");
  }

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search ticker…"
        className="h-8 w-40 rounded-md border border-border-input bg-surface px-3 text-xs text-text-primary placeholder:text-text-tertiary outline-none focus:border-brand sm:w-56"
      />
    </form>
  );
}
