import { PageContainer } from "@/components/layout/PageContainer";
import { DiscountRateSettingsForm } from "@/components/settings/DiscountRateSettingsForm";

export default function SettingsPage() {
  return (
    <PageContainer className="space-y-6 pb-12">
      <h1 className="pt-6 text-2xl font-semibold tracking-tight text-zinc-100">Settings</h1>
      <DiscountRateSettingsForm />
    </PageContainer>
  );
}
