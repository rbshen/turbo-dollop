import type { Metadata } from "next";

export const metadata: Metadata = { title: "Breadth" };

export default function BreadthLayout({ children }: { children: React.ReactNode }) {
  return children;
}
