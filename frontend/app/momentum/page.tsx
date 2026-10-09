"use client";

import { PageContainer } from "@/components/layout/PageContainer";
import { MomentumSection } from "@/components/momentum/MomentumSection";
import { PageHeader } from "@/components/ui/page-header";
import { Section } from "@/components/ui/section";
import { useEtfMomentum, useMomentum } from "@/lib/hooks/useMomentum";

const STOCK_TOP_N = 10;
const ETF_TOP_N = 5;

const RETURNS_NOTE =
  "Returns are calendar-month lookbacks (3, 6 and 12 months) from the prior month-end close; a baseline on a weekend or holiday uses the last close on or before that date. Last is the latest close, which is newer than the return end date.";

export default function MomentumPage() {
  return (
    <>
      <PageContainer className="space-y-6 pb-12">
        <PageHeader title="Momentum" />

        <MomentumSection
          title="Stock"
          useData={useMomentum}
          topN={STOCK_TOP_N}
          footnote={
            <>
              <p>{RETURNS_NOTE}</p>
              <p>
                Point-in-time caveat: today&apos;s Moat classification is used as the current filter — no claim is made about what each
                ticker&apos;s Moat rating would have been historically.
              </p>
            </>
          }
        />

        <MomentumSection
          title="ETF"
          useData={useEtfMomentum}
          topN={ETF_TOP_N}
          showMoatAndScore={false}
          footnote={
            <>
              <p>{RETURNS_NOTE}</p>
              <p>
                Price-only basis: split-adjusted closes, no dividends, so income-heavy funds are understated. Leveraged funds are included.
                The previous-month ranking uses today&apos;s ETF universe, not the universe of that date (not point-in-time).
              </p>
            </>
          }
        />

        <Section>
          <p className="text-xs text-text-tertiary">
            Ad hoc external research using Fathom&apos;s cached data as one input — not a Fathom product feature, not investment advice.
          </p>
        </Section>
      </PageContainer>
    </>
  );
}
