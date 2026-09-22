import type { Metadata } from "next";

import { BreadthSectorView } from "@/components/breadth/BreadthSectorView";

interface Props {
  params: Promise<{ sector: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { sector } = await params;
  return { title: `${sector.toUpperCase()} Breadth` };
}

export default async function BreadthSectorPage({ params }: Props) {
  const { sector } = await params;
  return <BreadthSectorView sector={sector.toUpperCase()} />;
}
