"use client";

import { CaretDown, CaretUp } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";

import { MOAT_TONE } from "@/components/ticker/MoatPill";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Status } from "@/components/ui/status";
import { useMoatCheck } from "@/lib/hooks/useMoatCheck";
import {
  compareToSet,
  criteriaLabel,
  damageSummary,
  hostnameOf,
  isMoatValue,
  ratingLabel,
  reportedBy,
  toView,
  whyInconclusive,
  type Cited,
  type MoatCheckView,
  type PassDetail,
  type SourceRead,
} from "@/lib/moatCheck";
import type { MoatValue } from "@/lib/overallScore";
import { cn } from "@/lib/utils";

// The Independent check card (docs/specs/moat-check.md, "What you see"). READ-ONLY: no write call, no Apply button, nothing here changes the
// saved Moat rating or any score. Every string a research run wrote is drawn as a React text node (no HTML, no Markdown); a source URL
// becomes a link only through safeHttpUrl (http / https), with the hostname as the link text. The collapsed sections start collapsed on
// every render and are not persisted.

const TITLE = "Independent check";

export function MoatCheckFrame({ children }: { children: ReactNode }) {
  return (
    <section aria-label={TITLE} data-testid="moat-check-card" className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      {children}
    </section>
  );
}

export function MoatCheckHeading() {
  return <h3 className="font-heading text-sm font-semibold text-text-primary">{TITLE}</h3>;
}

/** A source reference: the hostname as a link for an http(s) URL, the stored text as plain text otherwise, then the date. */
function Reference({ href, sourceText, date }: { href: string | null; sourceText: string | null; date: string | null }) {
  const parts: ReactNode[] = [];
  if (href) {
    parts.push(
      <a key="link" href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-text-primary">
        {hostnameOf(href)}
      </a>,
    );
  } else if (sourceText) {
    parts.push(<span key="text">{sourceText}</span>);
  }
  if (date) parts.push(<span key="date">{date}</span>);
  if (parts.length === 0) return null;
  return (
    <span className="break-words text-xs text-text-tertiary">
      {parts.flatMap((part, i) => (i === 0 ? [part] : [" · ", part]))}
    </span>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false); // collapsed on every render; never persisted
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="space-y-3 border-t border-border-subtle pt-3">
      <CollapsibleTrigger className="group flex w-full items-center justify-between gap-3 text-left text-sm text-text-secondary hover:text-text-primary">
        <span>{title}</span>
        <span className="flex shrink-0 items-center gap-1 text-xs text-text-tertiary">
          <span className="group-data-[panel-open]:hidden">Show</span>
          <span className="hidden group-data-[panel-open]:inline">Hide</span>
          <CaretDown size={12} aria-hidden="true" className="group-data-[panel-open]:hidden" />
          <CaretUp size={12} aria-hidden="true" className="hidden group-data-[panel-open]:block" />
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-3">{children}</CollapsibleContent>
    </Collapsible>
  );
}

function Tile({ label, caption, children }: { label: string; caption?: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-text-tertiary">{label}</dt>
      <dd className="mt-1 space-y-0.5">
        <div className="text-sm text-text-primary">{children}</div>
        {caption && <p className="text-xs text-text-tertiary">{caption}</p>}
      </dd>
    </div>
  );
}

function RatingPill({ rating }: { rating: string | null }) {
  if (isMoatValue(rating)) return <Status tone={MOAT_TONE[rating]}>{ratingLabel(rating)}</Status>;
  return <span>{rating ? ratingLabel(rating) : "—"}</span>;
}

function sourceChipText(source: SourceRead): string {
  return `${source.label}: ${source.rating === "unproven" ? "no cited fact" : source.rating}`;
}

function FactLine({ fact }: { fact: Cited | null }) {
  if (!fact) return <p className="text-sm text-text-tertiary">No cited fact.</p>;
  return (
    <p className="break-words text-sm text-text-body">
      {fact.text} <Reference href={fact.href} sourceText={fact.sourceText} date={fact.date} />
    </p>
  );
}

// --- stable: one reading ---------------------------------------------------------------------------------------------------------

function EvidenceCheck({ detail, proofBasis }: { detail: PassDetail; proofBasis: string | null }) {
  const basis = reportedBy(proofBasis);
  return (
    <div className="space-y-2 rounded-md border border-border-subtle p-4" role="group" aria-label="Evidence check">
      <p className="text-sm font-medium text-text-primary">
        Evidence check <span className="text-xs font-normal text-text-tertiary">Affects confidence only, never the rating.</span>
      </p>
      {detail.reading && <p className="text-sm text-text-body">Outcome reading: {detail.reading}</p>}
      <p className="break-words text-sm text-text-body">
        Supporting item: {detail.supportingItem ?? <span className="text-text-tertiary">none</span>}
      </p>
      {basis && (
        <>
          <p className="text-sm text-text-body">Reported by: {basis.who}</p>
          <p className="text-sm text-text-body">{basis.finding}</p>
        </>
      )}
      {detail.evidence.length > 0 && (
        <ul className="space-y-1 pt-1">
          {detail.evidence.map((item, i) => (
            <li key={i} className="break-words text-xs text-text-secondary">
              {item.level !== null && <span>Level {item.level} · </span>}
              {item.item} <Reference href={item.href} sourceText={item.sourceText} date={item.date} />
              {item.stale && <span className="text-text-tertiary"> · stale</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StableBody({ view, detail }: { view: MoatCheckView; detail: PassDetail }) {
  return (
    <>
      <EvidenceCheck detail={detail} proofBasis={view.proofBasis} />

      {detail.sources.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Sources of advantage">
          {detail.sources.map((source) => (
            <li key={source.key}>
              <Status tone={source.rating === "strong" ? "positive" : "neutral"}>{sourceChipText(source)}</Status>
            </li>
          ))}
        </ul>
      )}

      {detail.sources.length > 0 && (
        <Section title="Fact behind each source rating">
          <ul className="space-y-3">
            {detail.sources.map((source) => (
              <li key={source.key} className="space-y-1">
                <p className="text-sm text-text-primary">
                  {source.label} <span className="text-text-tertiary">{source.rating}</span>
                </p>
                <FactLine fact={source.fact} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {detail.narrative && <p className="break-words text-sm text-text-body">{detail.narrative}</p>}

      <Section title={damageSummary(detail.damage)}>
        {detail.damage.length === 0 ? (
          <p className="text-sm text-text-tertiary">No declines were found.</p>
        ) : (
          <ul className="space-y-3">
            {detail.damage.map((item, i) => (
              <li key={i} className="space-y-1">
                <p className="break-words text-sm text-text-primary">
                  {item.metric}
                  {item.change && <span className="text-text-secondary">: {item.change}</span>}
                  {item.period && <span className="text-text-tertiary"> ({item.period})</span>}
                </p>
                <p className="break-words text-sm text-text-body">
                  {item.counted === true ? "Counted against the rating" : item.counted === false ? "Not counted" : "Not stated whether it counted"}
                  {item.reason && `: ${item.reason}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Forward threats">
        <p className="text-xs text-text-tertiary">What could happen, not what has happened. Never changes the rating.</p>
        {detail.threats.length === 0 ? (
          <p className="text-sm text-text-tertiary">No threats were listed.</p>
        ) : (
          <ul className="space-y-4">
            {detail.threats.map((threat, i) => (
              <li key={i} className="space-y-1">
                <p className="break-words text-sm text-text-primary">
                  {threat.name} {threat.level && <span className="text-text-tertiary">{threat.level}</span>}
                </p>
                {threat.observed && <p className="break-words text-sm text-text-body">Seen so far: {threat.observed}</p>}
                {(threat.metric || threat.valueNow || threat.reviewLevel) && (
                  <p className="break-words text-xs text-text-secondary">
                    {threat.metric && <>Tripwire: {threat.metric}</>}
                    {threat.valueNow && <> · now {threat.valueNow}</>}
                    {threat.reviewLevel && <> · review at {threat.reviewLevel}</>}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <div className="space-y-1 border-t border-border-subtle pt-3">
        {detail.wouldLower && (
          <p className="break-words text-sm text-text-body">
            <span className="text-text-primary">Would lower it:</span> {detail.wouldLower}
          </p>
        )}
        {detail.wouldRaise && (
          <p className="break-words text-sm text-text-body">
            <span className="text-text-primary">Would raise it:</span> {detail.wouldRaise}
          </p>
        )}
      </div>

      {detail.evidenceNote && (
        <div className="break-words rounded-md border border-warn/40 bg-warn/10 p-3 text-sm text-warn" role="note">
          {detail.evidenceNote}
        </div>
      )}
    </>
  );
}

// --- inconclusive: two readings --------------------------------------------------------------------------------------------------

function PassColumn({ number, pass, storedRating }: { number: number; pass: PassDetail | null; storedRating: string | null }) {
  const rating = pass?.rating ?? storedRating;
  return (
    <div className="space-y-2 rounded-md border border-border-subtle p-4" role="group" aria-label={`Pass ${number}`}>
      <p className="text-sm font-medium text-text-primary">Pass {number}</p>
      <div className="text-sm">
        <RatingPill rating={rating} />
      </div>
      {pass?.reading && <p className="text-sm text-text-body">Outcome reading: {pass.reading}</p>}
      {pass?.strongest && (
        <div className="space-y-1">
          <p className="text-sm text-text-body">
            Strongest source: {pass.strongest.label} <span className="text-text-tertiary">{pass.strongest.rating}</span>
          </p>
          <FactLine fact={pass.strongest.fact} />
        </div>
      )}
      <p className="break-words text-sm text-text-body">
        Supporting item: {pass?.supportingItem ?? <span className="text-text-tertiary">none</span>}
      </p>
    </div>
  );
}

function InconclusiveBody({ view }: { view: MoatCheckView }) {
  const [first, second] = view.passes ?? [null, null];
  const why = whyInconclusive(view.passes, view.passRatings);
  return (
    <>
      {why && <p className="break-words text-sm text-text-body">{why}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        <PassColumn number={1} pass={first} storedRating={view.passRatings[0]} />
        <PassColumn number={2} pass={second} storedRating={view.passRatings[1]} />
      </div>
    </>
  );
}

// --- the card ---------------------------------------------------------------------------------------------------------------------

/** Presentational: the view arrives as a prop and `setRating` is the SAVED rating (never an unconfirmed selection). */
export function MoatCheckCardView({ view, setRating }: { view: MoatCheckView; setRating: MoatValue | null }) {
  const stable = view.status === "stable";
  const comparison = stable ? compareToSet(view.rating, setRating) : "unknown";
  const lowConfidence = view.confidence === "Low";
  const unverified = view.proofBasis === "company_reported_only";
  const meta = [!stable ? "passes disagree" : null, criteriaLabel(view.criteriaVersion), view.checkedDate ? `checked ${view.checkedDate}` : null].filter(
    Boolean,
  );
  const passThreats = view.passes ? view.passes.map((pass) => pass?.threatLevel ?? null) : [];

  return (
    <MoatCheckFrame>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <MoatCheckHeading />
        {meta.length > 0 && <p className="text-xs text-text-tertiary">{meta.join(" · ")}</p>}
      </header>

      {!view.criteriaIsCurrent && (
        <p className="text-xs text-warn">Checked under an older criteria version. Run it again for the current one.</p>
      )}

      <dl className="grid gap-x-10 gap-y-3 sm:grid-cols-3">
        <Tile label="Rating today" caption="observed evidence only">
          {stable ? <RatingPill rating={view.rating} /> : <span>Inconclusive</span>}
        </Tile>
        <Tile label="Evidence confidence">
          <span className={cn(lowConfidence && "text-warn")}>{view.confidence ?? "—"}</span>
        </Tile>
        <Tile label="Forward threat level" caption="not scored">
          {stable ? (
            <span>{view.threatLevel ?? "—"}</span>
          ) : (
            <span>
              {passThreats.length === 2 && passThreats.some(Boolean)
                ? `Pass 1: ${passThreats[0] ?? "—"} · Pass 2: ${passThreats[1] ?? "—"}`
                : "—"}
            </span>
          )}
        </Tile>
      </dl>

      {(comparison !== "unknown" || unverified) && (
        <div className="flex flex-wrap items-center gap-2">
          {comparison === "agrees" && <Status tone="neutral">Agrees with your rating</Status>}
          {comparison === "differs" && (
            <>
              <Status tone="neutral">Differs from your rating</Status>
              <span className="text-xs text-text-tertiary">Your rating: {ratingLabel(setRating)}</span>
            </>
          )}
          {comparison === "no_set_rating" && <Status tone="neutral">No set rating</Status>}
          {unverified && <Status tone="warn">Unverified by independent source</Status>}
        </div>
      )}

      {stable ? (
        view.detail ? (
          <StableBody view={view} detail={view.detail} />
        ) : (
          <p className="text-sm text-text-secondary">The detail of this check can&apos;t be displayed.</p>
        )
      ) : (
        <InconclusiveBody view={view} />
      )}

      <p className="border-t border-border-subtle pt-3 text-xs text-text-tertiary">Advisory only. Never changes your rating or any score.</p>
    </MoatCheckFrame>
  );
}

/** The card on the Moat tab: reads the newest check and draws it. `setRating` is the saved set rating. */
export function MoatCheckCard({ ticker, setRating }: { ticker: string; setRating: MoatValue | null }) {
  const { data, error } = useMoatCheck(ticker);

  if (error) {
    return (
      <MoatCheckFrame>
        <MoatCheckHeading />
        <p className="text-sm text-negative">Couldn&apos;t load Independent check — {error.message}</p>
      </MoatCheckFrame>
    );
  }
  // `null` is "never checked" (the endpoint answers JSON null); only `undefined` is "still loading".
  if (data === undefined) {
    return (
      <MoatCheckFrame>
        <MoatCheckHeading />
        <p className="animate-pulse text-sm text-text-tertiary">Loading…</p>
      </MoatCheckFrame>
    );
  }
  if (data === null) {
    return (
      <MoatCheckFrame>
        <MoatCheckHeading />
        <p className="text-sm text-text-secondary">
          Not checked yet. Run <code className="font-mono text-text-primary">/moat-check {ticker}</code> in Claude Code.
        </p>
      </MoatCheckFrame>
    );
  }
  const view = toView(data);
  if (!view) {
    return (
      <MoatCheckFrame>
        <MoatCheckHeading />
        <p className="text-sm text-text-secondary">This check can&apos;t be displayed.</p>
      </MoatCheckFrame>
    );
  }
  return <MoatCheckCardView view={view} setRating={setRating} />;
}
