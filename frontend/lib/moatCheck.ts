// Pure helpers behind the Independent check card (docs/specs/moat-check.md, "What you see"). Nothing here renders.
//
// The nested parts of a stored check are loosely typed on the server ON PURPOSE (a row from a later criteria version may have another
// shape), so everything below treats its input as `unknown`: the readers return null / empty / "unknown" for anything that is not what
// they expect and NEVER throw. All text comes back as plain strings for React text nodes; a URL becomes a link target only through
// `safeHttpUrl`.

import type { MoatCheckOut } from "@/lib/api/types";
import { MOAT_LABELS, type MoatValue } from "@/lib/overallScore";
import { pillLabel } from "@/lib/tierColor";

/** A stored list longer than this is cut: junk or a runaway record must not freeze the page. */
export const MAX_ITEMS = 50;

const MOAT_VALUES: readonly MoatValue[] = ["no_moat", "narrow_moat", "wide_moat"];

export function isMoatValue(value: unknown): value is MoatValue {
  return typeof value === "string" && (MOAT_VALUES as readonly string[]).includes(value);
}

/** The tier label for a Moat value ("Wide moat"); any other string is returned as given (plain text), anything else is "Unknown". */
export function ratingLabel(value: unknown): string {
  if (isMoatValue(value)) return pillLabel(MOAT_LABELS[value]);
  return typeof value === "string" && value.trim() ? value : "Unknown";
}

// --- links -----------------------------------------------------------------------------------------------------------------------

/** The absolute URL when `value` is an http: or https: URL, else null (javascript:, data:, file:, relative paths, junk). */
export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

/** The link text for a safe URL: its hostname without a leading "www.". */
export function hostnameOf(href: string): string {
  try {
    return new URL(href).hostname.replace(/^www\./, "");
  } catch {
    return href;
  }
}

// --- agrees / differs --------------------------------------------------------------------------------------------------------------

export type Comparison = "agrees" | "differs" | "no_set_rating" | "unknown";

/** The check rating against the SAVED set rating. "unknown" when the check rating is not one of the three Moat values (nothing to compare);
 * "no_set_rating" when the ticker has no saved rating. An unconfirmed selection on the segmented control is never passed in here. */
export function compareToSet(checkRating: unknown, setRating: MoatValue | null | undefined): Comparison {
  if (!isMoatValue(checkRating)) return "unknown";
  if (!isMoatValue(setRating)) return "no_set_rating";
  return checkRating === setRating ? "agrees" : "differs";
}

// --- tolerant readers --------------------------------------------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** A non-blank string, else null. */
function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value.slice(0, MAX_ITEMS) : [];
}

export const SOURCE_LABELS: Record<string, string> = {
  brand_monopoly: "Brand",
  switching_costs: "Switching costs",
  barriers_to_entry: "Barriers to entry",
  network_effect: "Network effect",
  economies_of_scale: "Scale",
};
const SOURCE_ORDER = Object.keys(SOURCE_LABELS);
const SOURCE_RANK: Record<string, number> = { strong: 4, moderate: 3, weak: 2, absent: 1, unproven: 0 };

export interface Cited {
  text: string;
  /** Present only for an http(s) source; the card links it, with the hostname as the link text. */
  href: string | null;
  /** The source as written, shown as plain text when it is not a safe link. */
  sourceText: string | null;
  date: string | null;
}

export interface SourceRead {
  key: string;
  label: string;
  /** strong / moderate / weak / absent / unproven, or whatever string was stored. */
  rating: string;
  fact: Cited | null;
}

export interface EvidenceItem {
  level: number | null;
  item: string;
  href: string | null;
  sourceText: string | null;
  date: string | null;
  stale: boolean;
}

export interface DamageItem {
  metric: string;
  change: string | null;
  period: string | null;
  /** true / false when the entry says yes / no; null when it says neither. */
  counted: boolean | null;
  reason: string | null;
}

export interface ThreatItem {
  name: string;
  level: string | null;
  observed: string | null;
  metric: string | null;
  valueNow: string | null;
  reviewLevel: string | null;
}

export interface PassDetail {
  rating: string | null;
  reading: string | null;
  confidence: string | null;
  proofBasis: string | null;
  sources: SourceRead[];
  strongest: SourceRead | null;
  supportingItem: string | null;
  evidence: EvidenceItem[];
  narrative: string | null;
  damage: DamageItem[];
  threats: ThreatItem[];
  threatLevel: string | null;
  wouldLower: string | null;
  wouldRaise: string | null;
  evidenceNote: string | null;
}

function readCited(raw: unknown): Cited | null {
  const rec = asRecord(raw);
  const text = rec && asText(rec.fact);
  if (!rec || !text) return null;
  const source = asText(rec.source);
  return { text, href: safeHttpUrl(source), sourceText: source, date: asText(rec.date) };
}

function readSources(ratings: unknown, facts: unknown): SourceRead[] {
  const ratingMap = asRecord(ratings);
  const factMap = asRecord(facts);
  if (!ratingMap && !factMap) return [];
  const keys = [...SOURCE_ORDER, ...Object.keys(ratingMap ?? {}).filter((k) => !SOURCE_ORDER.includes(k))].slice(0, MAX_ITEMS);
  return keys
    .filter((key) => ratingMap && key in ratingMap)
    .map((key) => ({
      key,
      label: SOURCE_LABELS[key] ?? key,
      rating: asText(ratingMap?.[key]) ?? "unproven",
      fact: readCited(factMap?.[key]),
    }));
}

function strongestOf(sources: SourceRead[]): SourceRead | null {
  let best: SourceRead | null = null;
  for (const source of sources) {
    const rank = (s: SourceRead) => (SOURCE_RANK[s.rating] ?? -1) * 2 + (s.fact ? 1 : 0);
    if (!best || rank(source) > rank(best)) best = source;
  }
  return best;
}

function readEvidence(raw: unknown): EvidenceItem[] {
  return asList(raw).flatMap((entry) => {
    const rec = asRecord(entry);
    const item = rec && asText(rec.item);
    if (!rec || !item) return [];
    const source = asText(rec.source);
    return [
      {
        level: typeof rec.level === "number" ? rec.level : null,
        item,
        href: safeHttpUrl(source),
        sourceText: source,
        date: asText(rec.date),
        stale: rec.stale === true,
      },
    ];
  });
}

function readDamage(raw: unknown): DamageItem[] {
  return asList(raw).flatMap((entry) => {
    const rec = asRecord(entry);
    const metric = rec && asText(rec.metric);
    if (!rec || !metric) return [];
    return [
      {
        metric,
        change: asText(rec.change),
        period: asText(rec.period),
        counted: rec.counted === "yes" ? true : rec.counted === "no" ? false : null,
        reason: asText(rec.reason),
      },
    ];
  });
}

function readThreats(raw: unknown): { level: string | null; threats: ThreatItem[] } {
  const block = asRecord(raw);
  if (!block) return { level: null, threats: [] };
  const threats = asList(block.threats).flatMap((entry) => {
    const rec = asRecord(entry);
    const name = rec && asText(rec.name);
    if (!rec || !name) return [];
    const tripwire = asRecord(rec.tripwire);
    return [
      {
        name,
        level: asText(rec.level),
        observed: asText(rec.observed_so_far),
        metric: asText(tripwire?.metric),
        valueNow: asText(tripwire?.value_now),
        reviewLevel: asText(tripwire?.review_level),
      },
    ];
  });
  return { level: asText(block.threat_level), threats };
}

/** One pass record (or the stable row's columns merged under it) as plain data; null when it is not an object at all. */
export function readPass(raw: unknown): PassDetail | null {
  const rec = asRecord(raw);
  if (!rec) return null;
  const sources = readSources(rec.sources_rating, rec.source_facts);
  const threats = readThreats(rec.forward_threats);
  return {
    rating: asText(rec.suggested_rating),
    reading: asText(rec.reading),
    confidence: asText(rec.evidence_confidence),
    proofBasis: asText(rec.proof_basis),
    sources,
    strongest: strongestOf(sources),
    supportingItem: asText(rec.outcome_supporting_item),
    evidence: readEvidence(rec.outcome_evidence),
    narrative: asText(rec.narrative),
    damage: readDamage(rec.observed_damage),
    threats: threats.threats,
    threatLevel: threats.level,
    wouldLower: asText(rec.would_lower),
    wouldRaise: asText(rec.would_raise),
    evidenceNote: asText(rec.evidence_note),
  };
}

export interface MoatCheckView {
  ticker: string;
  /** YYYY-MM-DD */
  checkedDate: string | null;
  criteriaVersion: string | null;
  criteriaIsCurrent: boolean;
  status: "stable" | "inconclusive";
  /** The reconciled rating as stored (null when inconclusive); `isMoatValue` before treating it as one of the three. */
  rating: string | null;
  confidence: string | null;
  proofBasis: string | null;
  threatLevel: string | null;
  /** Stable: pass 1's detail (its record, with the row's detail columns as the fallback). */
  detail: PassDetail | null;
  /** Inconclusive: each pass; a pass whose record could not be read is null and the card falls back to its stored rating. */
  passes: [PassDetail | null, PassDetail | null] | null;
  passRatings: [string | null, string | null];
}

/** The API row as plain data for the card, or null when it is not a readable check (not an object, or a status this card does not know). */
export function toView(raw: MoatCheckOut | unknown): MoatCheckView | null {
  const row = asRecord(raw);
  if (!row) return null;
  const status = row.status;
  if (status !== "stable" && status !== "inconclusive") return null;
  const ticker = asText(row.ticker);
  if (!ticker) return null;

  const columns = {
    sources_rating: row.sources_rating,
    source_facts: row.source_facts,
    observed_damage: row.observed_damage,
    forward_threats: row.forward_threats,
    would_lower: row.would_lower,
    would_raise: row.would_raise,
    evidence_note: row.evidence_note,
    suggested_rating: row.rating,
    evidence_confidence: row.evidence_confidence,
    proof_basis: row.proof_basis,
  };
  const pass1 = asRecord(row.pass1);
  const detail = status === "stable" ? readPass({ ...columns, ...(pass1 ?? {}) }) : null;
  const passes: MoatCheckView["passes"] = status === "inconclusive" ? [readPass(row.pass1), readPass(row.pass2)] : null;

  return {
    ticker,
    checkedDate: asText(row.checked_at)?.slice(0, 10) ?? null,
    criteriaVersion: asText(row.criteria_version),
    criteriaIsCurrent: row.criteria_is_current !== false,
    status,
    rating: asText(row.rating),
    confidence: asText(row.evidence_confidence),
    proofBasis: asText(row.proof_basis),
    threatLevel: asText(row.threat_level) ?? detail?.threatLevel ?? null,
    detail,
    passes,
    passRatings: [asText(row.pass1_rating), asText(row.pass2_rating)],
  };
}

/** "criteria v5.2" from "moat-criteria-v5.2"; any other string is shown as stored. */
export function criteriaLabel(version: string | null): string | null {
  if (!version) return null;
  const match = /^moat-criteria-(v.+)$/.exec(version);
  return match ? `criteria ${match[1]}` : version;
}

/** "N found, M counted against the rating" for the declines section title. */
export function damageSummary(damage: DamageItem[]): string {
  const counted = damage.filter((d) => d.counted === true).length;
  return `Declines reviewed: ${damage.length} found, ${counted} counted against the rating`;
}

/** The one-line reason two passes disagreed, from the two ratings and readings; null when nothing can be said. */
export function whyInconclusive(passes: MoatCheckView["passes"], ratings: MoatCheckView["passRatings"]): string | null {
  if (!passes) return null;
  const part = (n: number, pass: PassDetail | null, stored: string | null) => {
    const rating = pass?.rating ?? stored;
    if (!rating) return null;
    return `pass ${n} rated ${ratingLabel(rating)}${pass?.reading ? ` on a "${pass.reading}" reading` : ""}`;
  };
  const first = part(1, passes[0], ratings[0]);
  const second = part(2, passes[1], ratings[1]);
  if (!first || !second) return null;
  const sameReading = passes[0]?.reading && passes[0].reading === passes[1]?.reading;
  const tail = sameReading ? "Both read the outcome check the same way but weighed the sources differently." : "";
  return `${first.charAt(0).toUpperCase()}${first.slice(1)}; ${second}.${tail ? ` ${tail}` : ""}`;
}

/** Who reported the proof that the moat is working, from `proof_basis`; null for a value this card does not know. */
export function reportedBy(proofBasis: string | null): { who: string; finding: string } | null {
  if (proofBasis === "independent") {
    return { who: "Independent", finding: "Independent support found: at least one item supporting the reading comes from a source other than the company." };
  }
  if (proofBasis === "company_reported_only") {
    return { who: "Company-reported", finding: "No independent support found: the proof comes from the company alone." };
  }
  return null;
}
