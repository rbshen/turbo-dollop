import { PageContainer } from "@/components/layout/PageContainer";
import { DiscountRateSettingsForm } from "@/components/settings/DiscountRateSettingsForm";
import { MoatSettingsForm } from "@/components/settings/MoatSettingsForm";
import { WatchlistSettingsForm } from "@/components/settings/WatchlistSettingsForm";

export default function SettingsPage() {
  return (
    <PageContainer className="space-y-6 pb-12">
      <h1 className="font-heading pt-6 text-2xl font-semibold tracking-tight text-zinc-100">Settings</h1>
      <DiscountRateSettingsForm />
      <MoatSettingsForm />
      <WatchlistSettingsForm />
    </PageContainer>
  );
}
