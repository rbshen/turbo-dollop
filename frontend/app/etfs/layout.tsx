import type { Metadata } from "next";

export const metadata: Metadata = { title: "ETFs" };

export default function EtfsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
