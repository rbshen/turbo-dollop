import type { Metadata } from "next";

export const metadata: Metadata = { title: "Technical Ideas" };

export default function TechnicalIdeasLayout({ children }: { children: React.ReactNode }) {
  return children;
}
