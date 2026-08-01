"use client";

import { useNews } from "@/lib/hooks/useNews";
import type { NewsArticle } from "@/lib/api/types";

interface Props {
  ticker: string;
}

function formatPublishedAt(raw: string): string {
  // FMP's raw "YYYY-MM-DD HH:MM:SS" -- no documented timezone, so this is
  // rendered as a plain local-format timestamp, not converted.
  const parsed = new Date(raw.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function ArticleCard({ article }: { article: NewsArticle }) {
  return (
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex gap-4 rounded-lg border border-border-card bg-surface p-4 transition-colors hover:border-brand"
    >
      {article.image && (
        // Arbitrary external publisher images, not a configured next/image domain.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={article.image}
          alt=""
          loading="lazy"
          className="hidden h-20 w-28 shrink-0 rounded-md object-cover sm:block"
        />
      )}
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-heading text-sm font-semibold text-text-primary">{article.title}</p>
        <p className="line-clamp-2 text-xs text-text-tertiary">{article.snippet}</p>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-text-secondary">
          <span className="font-medium">{article.publisher}</span>
          <span className="text-text-tertiary">·</span>
          <span className="text-text-tertiary">{article.site}</span>
          <span className="text-text-tertiary">·</span>
          <span className="font-mono text-text-tertiary">{formatPublishedAt(article.published_at)}</span>
        </div>
      </div>
    </a>
  );
}

export function NewsSentimentTab({ ticker }: Props) {
  const { data, error } = useNews(ticker);

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
        <p className="text-sm text-text-tertiary">No recent news found for {ticker}.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-6">
      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-text-secondary">News</h2>
        <div className="space-y-3">
          {data.articles.map((article) => (
            <ArticleCard key={article.url} article={article} />
          ))}
        </div>
      </div>
    </div>
  );
}
