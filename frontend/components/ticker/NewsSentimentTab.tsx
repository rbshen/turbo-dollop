"use client";

import { useNewsSentiment } from "@/lib/hooks/useNewsSentiment";
import { SentimentDistributionBar } from "@/components/ticker/SentimentDistributionBar";
import { sentimentBadgeClass, sentimentBadgeStyle } from "@/lib/sentimentColor";
import type { NewsSentimentArticle } from "@/lib/api/types";

interface Props {
  ticker: string;
}

function formatRelativeTime(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  const diffMs = Date.now() - parsed.getTime();
  const diffMinutes = Math.round(diffMs / 60_000);
  if (diffMinutes < 60) return `${Math.max(diffMinutes, 0)}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function SentimentBadge({ label, score }: { label: string; score: number }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${sentimentBadgeClass(label)}`}
      style={sentimentBadgeStyle(label)}
    >
      {label} <span className="font-mono tabular-nums">{score.toFixed(2)}</span>
    </span>
  );
}

function ArticleRow({ article }: { article: NewsSentimentArticle }) {
  return (
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex flex-col gap-2 rounded-lg border border-border-card bg-surface p-4 transition-colors hover:border-brand"
    >
      <p className="font-heading text-sm font-semibold text-text-primary">{article.title}</p>
      {article.summary && <p className="line-clamp-2 text-xs text-text-tertiary">{article.summary}</p>}
      <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
        <span className="font-medium">{article.source}</span>
        <span className="text-text-tertiary">·</span>
        <span className="font-mono text-text-tertiary">{formatRelativeTime(article.published_at)}</span>
        <span className="text-text-tertiary">·</span>
        <span className="font-mono tabular-nums text-text-tertiary">
          relevance {article.ticker_relevance_score.toFixed(2)}
        </span>
        <SentimentBadge label={article.ticker_sentiment_label} score={article.ticker_sentiment_score} />
      </div>
    </a>
  );
}

export function NewsSentimentTab({ ticker }: Props) {
  const { data, error } = useNewsSentiment(ticker);

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-negative">
          Couldn&apos;t load {ticker} — {error.message}
        </span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-text-tertiary animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  if (data.articles.length === 0) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-sm text-text-tertiary">No recent news/sentiment coverage found for {ticker}.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-6">
      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-text-secondary">Sentiment</h2>
        <SentimentDistributionBar distribution={data.distribution} />
      </div>
      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-text-secondary">News</h2>
        <div className="space-y-3">
          {data.articles.map((article) => (
            <ArticleRow key={article.url} article={article} />
          ))}
        </div>
      </div>
    </div>
  );
}
