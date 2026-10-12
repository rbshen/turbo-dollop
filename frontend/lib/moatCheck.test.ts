import { describe, expect, it } from "vitest";

import {
  MAX_ITEMS,
  compareToSet,
  criteriaLabel,
  damageSummary,
  hostnameOf,
  isMoatValue,
  ratingLabel,
  readPass,
  reportedBy,
  safeHttpUrl,
  toView,
  whyInconclusive,
} from "@/lib/moatCheck";

const record = (over: Record<string, unknown> = {}) => ({
  suggested_rating: "wide_moat",
  reading: "supported",
  evidence_confidence: "Medium",
  proof_basis: "independent",
  sources_rating: { brand_monopoly: "strong", switching_costs: "moderate", barriers_to_entry: "weak", network_effect: "absent", economies_of_scale: "unproven" },
  source_facts: {
    brand_monopoly: { fact: "share 31%", source: "https://www.example.com/a", date: "2026-06-01" },
    switching_costs: { fact: "renewal 92%", source: "https://example.org/b", date: "2026-05-01" },
    barriers_to_entry: { fact: "rivals list on the same sites", source: "https://example.org/c", date: "2026-04-01" },
    network_effect: { fact: "no network effect seen", source: "https://example.org/d", date: "2026-03-01" },
    economies_of_scale: null,
  },
  outcome_supporting_item: "share held",
  outcome_evidence: [{ level: 1, item: "share held", source: "https://example.org/e", date: "2026-05", stale: false }],
  narrative: "Observed facts only.",
  observed_damage: [
    { metric: "Net margin", change: "from 10% to 9%", period: "2024-2025", counted: "no", reason: "cost side" },
    { metric: "Share", change: "from 32% to 31%", period: "2025", counted: "yes", reason: "lost share" },
  ],
  forward_threats: {
    threat_level: "Moderate",
    threats: [{ name: "Rivals", level: "Moderate", observed_so_far: "Share 31%", tripwire: { metric: "share", value_now: "31%", review_level: "below 27.9%" } }],
  },
  would_lower: "Share below 27.9%.",
  would_raise: "Independent proof of retention.",
  evidence_note: null,
  ...over,
});

const stableRow = (over: Record<string, unknown> = {}) => ({
  ticker: "PM",
  checked_at: "2026-10-12T10:00:00",
  criteria_version: "moat-criteria-v5.2",
  criteria_is_current: true,
  status: "stable",
  rating: "wide_moat",
  pass1_rating: "wide_moat",
  pass2_rating: "wide_moat",
  evidence_confidence: "Medium",
  proof_basis: "independent",
  threat_level: "Moderate",
  sources_rating: null,
  source_facts: null,
  observed_damage: null,
  forward_threats: null,
  would_lower: null,
  would_raise: null,
  evidence_note: null,
  pass1: record(),
  pass2: null,
  ...over,
});

describe("safeHttpUrl", () => {
  it.each([
    ["https://example.com/a", "https://example.com/a"],
    ["http://example.com", "http://example.com/"],
    ["  https://example.com/x?y=1#z ", "https://example.com/x?y=1#z"],
  ])("accepts %s", (input, out) => expect(safeHttpUrl(input)).toBe(out));

  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://example.com",
    "vbscript:x",
    "//example.com/path",
    "/relative/path",
    "example.com",
    "",
    "not a url",
    null,
    undefined,
    42,
    {},
    ["https://example.com"],
  ])("refuses %j", (input) => expect(safeHttpUrl(input)).toBeNull());

  it("gives the hostname without a leading www as the link text", () => {
    expect(hostnameOf("https://www.example.com/a")).toBe("example.com");
    expect(hostnameOf("https://news.example.org/a")).toBe("news.example.org");
  });
});

describe("compareToSet", () => {
  it("agrees and differs on the three Moat values", () => {
    expect(compareToSet("wide_moat", "wide_moat")).toBe("agrees");
    expect(compareToSet("narrow_moat", "wide_moat")).toBe("differs");
    expect(compareToSet("no_moat", "narrow_moat")).toBe("differs");
  });
  it("has no set rating to compare with", () => {
    expect(compareToSet("wide_moat", null)).toBe("no_set_rating");
    expect(compareToSet("wide_moat", undefined)).toBe("no_set_rating");
  });
  it("is unknown for a check rating that is not one of the three values", () => {
    for (const bad of [null, undefined, "huge_moat", "", 3, {}, "Wide Moat"]) expect(compareToSet(bad, "wide_moat")).toBe("unknown");
  });
});

describe("labels", () => {
  it("uses the tier labels and shows an unknown rating as plain text", () => {
    expect(ratingLabel("wide_moat")).toBe("Wide moat");
    expect(ratingLabel("no_moat")).toBe("No moat");
    expect(ratingLabel("mega_moat")).toBe("mega_moat");
    expect(ratingLabel(null)).toBe("Unknown");
    expect(isMoatValue("narrow_moat")).toBe(true);
    expect(isMoatValue("Narrow Moat")).toBe(false);
  });
  it("shortens the criteria version and leaves another string alone", () => {
    expect(criteriaLabel("moat-criteria-v5.2")).toBe("criteria v5.2");
    expect(criteriaLabel("something-else")).toBe("something-else");
    expect(criteriaLabel(null)).toBeNull();
  });
  it("says who reported the proof", () => {
    expect(reportedBy("independent")?.who).toBe("Independent");
    expect(reportedBy("company_reported_only")?.who).toBe("Company-reported");
    expect(reportedBy("company_reported_only")?.finding).toMatch(/No independent support/);
    expect(reportedBy("???")).toBeNull();
    expect(reportedBy(null)).toBeNull();
  });
});

describe("toView: a good row", () => {
  it("reads a stable row from pass 1's record", () => {
    const view = toView(stableRow())!;
    expect(view.status).toBe("stable");
    expect(view.rating).toBe("wide_moat");
    expect(view.checkedDate).toBe("2026-10-12");
    expect(view.criteriaIsCurrent).toBe(true);
    const detail = view.detail!;
    expect(detail.sources.map((s) => s.key)).toEqual(["brand_monopoly", "switching_costs", "barriers_to_entry", "network_effect", "economies_of_scale"]);
    expect(detail.sources[0].fact).toEqual({ text: "share 31%", href: "https://www.example.com/a", sourceText: "https://www.example.com/a", date: "2026-06-01" });
    expect(detail.sources[4]).toMatchObject({ rating: "unproven", fact: null });
    expect(detail.strongest?.key).toBe("brand_monopoly");
    expect(detail.supportingItem).toBe("share held");
    expect(detail.evidence).toHaveLength(1);
    expect(damageSummary(detail.damage)).toBe("Declines reviewed: 2 found, 1 counted against the rating");
    expect(detail.threats[0]).toMatchObject({ name: "Rivals", metric: "share", valueNow: "31%", reviewLevel: "below 27.9%" });
    expect(detail.wouldLower).toBe("Share below 27.9%.");
  });

  it("falls back to the row's detail columns when the record is missing", () => {
    const rec = record();
    const view = toView(
      stableRow({
        pass1: null,
        sources_rating: rec.sources_rating,
        source_facts: rec.source_facts,
        observed_damage: rec.observed_damage,
        forward_threats: rec.forward_threats,
        would_lower: "col lower",
      }),
    )!;
    expect(view.detail?.sources).toHaveLength(5);
    expect(view.detail?.damage).toHaveLength(2);
    expect(view.detail?.wouldLower).toBe("col lower");
    expect(view.detail?.supportingItem).toBeNull();
  });

  it("reads an inconclusive row's two passes and builds the why line", () => {
    const view = toView(
      stableRow({
        status: "inconclusive",
        rating: null,
        pass1_rating: "wide_moat",
        pass2_rating: "narrow_moat",
        evidence_confidence: "Low",
        pass1: record(),
        pass2: record({ suggested_rating: "narrow_moat", reading: "neutral" }),
      }),
    )!;
    expect(view.status).toBe("inconclusive");
    expect(view.detail).toBeNull();
    expect(view.passes?.map((p) => p?.rating)).toEqual(["wide_moat", "narrow_moat"]);
    expect(whyInconclusive(view.passes, view.passRatings)).toBe('Pass 1 rated Wide moat on a "supported" reading; pass 2 rated Narrow moat on a "neutral" reading.');
  });

  it("says when both passes read the outcome the same way", () => {
    const view = toView(stableRow({ status: "inconclusive", rating: null, pass2: record({ suggested_rating: "narrow_moat" }), pass2_rating: "narrow_moat" }))!;
    expect(whyInconclusive(view.passes, view.passRatings)).toMatch(/weighed the sources differently/);
  });

  it("uses the stored pass ratings for the why line when a record is unreadable", () => {
    const view = toView(stableRow({ status: "inconclusive", rating: null, pass1: "junk", pass2: 7, pass1_rating: "wide_moat", pass2_rating: "no_moat" }))!;
    expect(view.passes).toEqual([null, null]);
    expect(whyInconclusive(view.passes, view.passRatings)).toBe("Pass 1 rated Wide moat; pass 2 rated No moat.");
  });
});

describe("toView: junk shapes never throw", () => {
  it.each([null, undefined, 42, "text", true, [], [1, 2], {}, { status: "weird", ticker: "PM" }, { status: "stable" }, { status: "stable", ticker: "" }])(
    "is not a readable check: %j",
    (input) => expect(toView(input)).toBeNull(),
  );

  it("reads a stable row whose nested parts are all junk as an empty detail", () => {
    const view = toView(
      stableRow({
        sources_rating: "x",
        source_facts: 5,
        observed_damage: { a: 1 },
        forward_threats: [],
        would_lower: 7,
        would_raise: ["a"],
        evidence_note: { n: 1 },
        pass1: "str",
        criteria_version: 5,
        checked_at: 20261012,
        threat_level: 3,
        evidence_confidence: null,
      }),
    )!;
    expect(view.detail).toMatchObject({ sources: [], damage: [], threats: [], wouldLower: null, wouldRaise: null, evidenceNote: null, supportingItem: null });
    expect(view.checkedDate).toBeNull();
    expect(view.criteriaVersion).toBeNull();
    expect(view.threatLevel).toBeNull();
  });

  it("skips malformed list entries and keeps the good ones", () => {
    const detail = readPass(
      record({
        outcome_evidence: [null, 5, "x", { item: "" }, { item: "good", level: "one", stale: "yes" }],
        observed_damage: [{}, { metric: "m", counted: "maybe" }, null],
        forward_threats: { threats: [null, { name: "" }, { name: "t", tripwire: "junk" }] },
        source_facts: { brand_monopoly: { fact: "", source: 5 }, switching_costs: "x" },
      }),
    )!;
    expect(detail.evidence).toEqual([{ level: null, item: "good", href: null, sourceText: null, date: null, stale: false }]);
    expect(detail.damage).toEqual([{ metric: "m", change: null, period: null, counted: null, reason: null }]);
    expect(detail.threats).toEqual([{ name: "t", level: null, observed: null, metric: null, valueNow: null, reviewLevel: null }]);
    expect(detail.sources.find((s) => s.key === "brand_monopoly")?.fact).toBeNull();
  });

  it("cuts a runaway list", () => {
    const many = Array.from({ length: 5000 }, (_, i) => ({ metric: `m${i}`, counted: "no" }));
    expect(readPass(record({ observed_damage: many }))!.damage).toHaveLength(MAX_ITEMS);
  });

  it("keeps hostile text as plain strings and refuses an unsafe link", () => {
    const detail = readPass(
      record({
        source_facts: { brand_monopoly: { fact: "<img src=x onerror=alert(1)>", source: "javascript:alert(1)", date: "<b>d</b>" } },
        sources_rating: { brand_monopoly: "strong" },
      }),
    )!;
    expect(detail.sources[0].fact).toEqual({ text: "<img src=x onerror=alert(1)>", href: null, sourceText: "javascript:alert(1)", date: "<b>d</b>" });
  });

  it("treats a missing or odd criteria_is_current as current only unless it is false", () => {
    expect(toView(stableRow({ criteria_is_current: false }))!.criteriaIsCurrent).toBe(false);
    expect(toView(stableRow({ criteria_is_current: undefined }))!.criteriaIsCurrent).toBe(true);
  });
});
