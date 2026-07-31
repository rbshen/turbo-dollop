import { ComingSoonPanel } from "@/components/ticker/ComingSoonPanel";

// Empty placeholder shell per the remodel's explicit scope -- no
// news-headline wiring, no sentiment card, no data fetching. Card 1
// ("News & Analyst Sentiment") and Card 2 (the dashed-border, honest-
// framing "aggregate mention data" disclaimer card) from the design
// handoff are not built yet.
export function NewsSentimentTab() {
  return (
    <div className="py-6">
      <ComingSoonPanel label="News & Sentiment" />
    </div>
  );
}
