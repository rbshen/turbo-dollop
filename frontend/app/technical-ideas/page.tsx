"use client";

import { PageContainer } from "@/components/layout/PageContainer";
import { WarrenWatchSection } from "@/components/technical-ideas/WarrenWatchSection";
import { PageHeader } from "@/components/ui/page-header";

export default function TechnicalIdeasPage() {
  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader title="Technical Ideas" />
      <WarrenWatchSection />
    </PageContainer>
  );
}
