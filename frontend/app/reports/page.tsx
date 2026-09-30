import type { Metadata } from "next";

import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/page-header";

export const metadata: Metadata = { title: "Reports" };

export default function ReportsPage() {
  return (
    <PageContainer>
      <PageHeader title="Reports" />
      <div className="flex flex-1 items-center justify-center py-20">
        <p className="text-sm text-text-tertiary">Reports — coming soon</p>
      </div>
    </PageContainer>
  );
}
