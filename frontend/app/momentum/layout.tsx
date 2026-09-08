import type { Metadata } from "next";

export const metadata: Metadata = { title: "Momentum" };

export default function MomentumLayout({ children }: { children: React.ReactNode }) {
  return children;
}
