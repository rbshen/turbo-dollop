// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MoatCheckBoundary } from "@/components/ticker/MoatCheckBoundary";
import { MoatCheckCard } from "@/components/ticker/MoatCheckCard";

const apiPut = vi.fn();
const apiPost = vi.fn();
let hook: { data?: unknown; error?: Error };

vi.mock("@/lib/hooks/useMoatCheck", () => ({ useMoatCheck: () => hook }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPut: (...args: unknown[]) => apiPut(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
}));

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
  outcome_supporting_item: "share held at 31%",
  outcome_evidence: [
    { level: 1, item: "share held at 31%", source: "https://news.example.net/e", date: "2026-05", stale: false },
    { level: 3, item: "older call figure", source: "https://example.com/f", date: "2024-01", stale: true },
  ],
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

const row = (over: Record<string, unknown> = {}) => ({
  ticker: "AAPL",
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

const inconclusive = (over: Record<string, unknown> = {}) =>
  row({
    status: "inconclusive",
    rating: null,
    pass1_rating: "wide_moat",
    pass2_rating: "narrow_moat",
    evidence_confidence: "Low",
    threat_level: null,
    pass1: record({ forward_threats: { threat_level: "High", threats: [] } }),
    pass2: record({ suggested_rating: "narrow_moat", reading: "neutral", outcome_supporting_item: "pass two item", forward_threats: { threat_level: "Moderate", threats: [] } }),
    ...over,
  });

beforeEach(() => {
  hook = { data: row() };
  apiPut.mockReset();
  apiPost.mockReset();
});
afterEach(cleanup);

const text = () => document.body.textContent ?? "";
const open = (name: RegExp) => fireEvent.click(screen.getByRole("button", { name }));

describe("states", () => {
  it("is loading while the data is undefined and there is no error, and not 'Not checked yet'", () => {
    hook = { data: undefined };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("Loading…");
    expect(text()).not.toContain("Not checked yet");
  });

  it("is 'Not checked yet' for JSON null, with the command to run for this ticker", () => {
    hook = { data: null };
    render(<MoatCheckCard ticker="AAPL" setRating={null} />);
    expect(screen.getByRole("heading", { level: 3, name: "Independent check" })).toBeInTheDocument();
    expect(text()).toContain("Not checked yet. Run /moat-check AAPL in Claude Code.");
    expect(text()).not.toContain("Loading");
  });

  it("shows the load error", () => {
    hook = { error: new Error("boom") };
    render(<MoatCheckCard ticker="AAPL" setRating={null} />);
    expect(text()).toContain("Couldn't load Independent check — boom");
  });

  it.each([{ status: "weird", ticker: "AAPL" }, "text", 42, [], {}])("says an unreadable row can't be displayed: %j", (junk) => {
    hook = { data: junk };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("This check can't be displayed.");
  });

  it("an unreadable stored row cannot take down the page: the boundary shows a fallback and the siblings stay", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Boom(): never {
      throw new Error("bad row");
    }
    render(
      <div>
        <p>rating selector</p>
        <MoatCheckBoundary>
          <Boom />
        </MoatCheckBoundary>
      </div>,
    );
    expect(text()).toContain("rating selector");
    expect(text()).toContain("This check can't be displayed.");
    expect(screen.getByRole("heading", { name: "Independent check" })).toBeInTheDocument();
    spy.mockRestore();
  });

  it("a row whose nested parts are all junk still draws the card without throwing", () => {
    hook = {
      data: row({ sources_rating: "x", source_facts: 5, observed_damage: { a: 1 }, forward_threats: [], would_lower: 7, pass1: "str", evidence_note: { n: 1 }, checked_at: 5 }),
    };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(screen.getByRole("heading", { name: "Independent check" })).toBeInTheDocument();
    expect(text()).toContain("Advisory only. Never changes your rating or any score.");
  });
});

describe("a stable check", () => {
  it("shows the header, the three tiles with their captions and the footer", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("criteria v5.2 · checked 2026-10-12");
    expect(text()).not.toContain("passes disagree");
    for (const label of ["Rating today", "observed evidence only", "Evidence confidence", "Forward threat level", "not scored"]) expect(text()).toContain(label);
    expect(within(screen.getByTestId("moat-check-card")).getByText("Wide moat")).toBeInTheDocument();
    expect(text()).toContain("Medium");
    expect(text()).toContain("Moderate");
    expect(text()).toContain("Advisory only. Never changes your rating or any score.");
  });

  it("says Agrees when the check rating equals the saved rating, with a neutral pill", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    const pill = screen.getByText("Agrees with your rating");
    expect(pill.className).toMatch(/surface-2|neutral/);
    expect(text()).not.toContain("Differs");
  });

  it("says Differs, in the same neutral tone as Agrees, and names the saved rating", () => {
    const { unmount } = render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    const agrees = screen.getByText("Agrees with your rating").className;
    unmount();
    render(<MoatCheckCard ticker="AAPL" setRating="narrow_moat" />);
    expect(screen.getByText("Differs from your rating").className).toBe(agrees);
    expect(text()).toContain("Your rating: Narrow moat");
  });

  it("recomputes against the saved rating it is given", () => {
    const { rerender } = render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("Agrees with your rating");
    rerender(<MoatCheckCard ticker="AAPL" setRating="no_moat" />);
    expect(text()).toContain("Differs from your rating");
    expect(text()).toContain("Your rating: No moat");
    rerender(<MoatCheckCard ticker="AAPL" setRating={null} />);
    expect(text()).toContain("No set rating");
    expect(text()).not.toMatch(/Agrees|Differs/);
  });

  it("shows no agrees/differs pill for a check rating it does not know", () => {
    hook = { data: row({ rating: "mega_moat" }) };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("mega_moat");
    expect(text()).not.toMatch(/Agrees|Differs|No set rating/);
  });

  it("flags company-reported proof with the Unverified pill and a warn-toned Low confidence", () => {
    hook = { data: row({ proof_basis: "company_reported_only", evidence_confidence: "Low", pass1: record({ proof_basis: "company_reported_only", evidence_confidence: "Low" }) }) };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(screen.getByText("Unverified by independent source").className).toMatch(/warn/);
    expect(screen.getByText("Low").className).toMatch(/text-warn/);
    expect(text()).toContain("No independent support found");
    expect(text()).toContain("Reported by: Company-reported");
  });

  it("does not warn-tone a Medium confidence and shows no Unverified pill for independent proof", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(screen.getByText("Medium").className).not.toMatch(/warn/);
    expect(text()).not.toContain("Unverified");
    expect(text()).toContain("Reported by: Independent");
    expect(text()).toContain("Independent support found");
  });

  it("shows the Evidence check box: reading, supporting item, who reported it, and the outcome evidence with hostnames and stale marks", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    const box = screen.getByRole("group", { name: "Evidence check" });
    expect(box.textContent).toContain("Affects confidence only, never the rating.");
    expect(box.textContent).toContain("Outcome reading: supported");
    expect(box.textContent).toContain("Supporting item: share held at 31%");
    expect(within(box).getByRole("link", { name: "news.example.net" })).toHaveAttribute("href", "https://news.example.net/e");
    expect(box.textContent).toContain("older call figure");
    expect(box.textContent).toContain("stale");
  });

  it("shows the five source pills, 'no cited fact' for an unproven one", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    const list = screen.getByRole("list", { name: "Sources of advantage" });
    const items = within(list).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["Brand: strong", "Switching costs: moderate", "Barriers to entry: weak", "Network effect: absent", "Scale: no cited fact"]);
  });

  it("shows the narrative, the would-lower and would-raise lines, and no banner without an evidence note", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("Observed facts only.");
    expect(text()).toContain("Would lower it: Share below 27.9%.");
    expect(text()).toContain("Would raise it: Independent proof of retention.");
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("shows the evidence note as a warn-toned banner", () => {
    hook = { data: row({ pass1: record({ evidence_note: "No independent retention data found." }) }) };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    const note = screen.getByRole("note");
    expect(note.textContent).toBe("No independent retention data found.");
    expect(note.className).toMatch(/warn/);
  });

  it("says when it was checked under an older criteria version", () => {
    hook = { data: row({ criteria_is_current: false, criteria_version: "moat-criteria-v5.1" }) };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("criteria v5.1");
    expect(text()).toContain("Checked under an older criteria version.");
  });

  it("does not say so for a current row", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).not.toContain("older criteria version");
  });
});

describe("collapsed sections", () => {
  const TITLES = [/Fact behind each source rating/, /Declines reviewed: 2 found, 1 counted against the rating/, /^Forward threats/];

  it("start collapsed: none of their contents are on the page", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    for (const title of TITLES) expect(screen.getByRole("button", { name: title })).toHaveAttribute("aria-expanded", "false");
    expect(text()).not.toContain("renewal 92%");
    expect(text()).not.toContain("lost share");
    expect(text()).not.toContain("What could happen, not what has happened");
  });

  it("opens the facts: name, rating, fact and a hostname link", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    open(/Fact behind each source rating/);
    expect(text()).toContain("renewal 92%");
    expect(screen.getAllByRole("link", { name: "example.com" }).map((a) => a.getAttribute("href"))).toContain("https://www.example.com/a");
    expect(text()).toContain("No cited fact.");
  });

  it("opens the declines: each entry says whether it counted and why", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    open(/Declines reviewed/);
    expect(text()).toContain("Net margin: from 10% to 9% (2024-2025)");
    expect(text()).toContain("Not counted: cost side");
    expect(text()).toContain("Counted against the rating: lost share");
  });

  it("opens the forward threats with the standing line and each tripwire", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    open(/^Forward threats/);
    expect(text()).toContain("What could happen, not what has happened. Never changes the rating.");
    expect(text()).toContain("Rivals");
    expect(text()).toContain("Seen so far: Share 31%");
    expect(text()).toContain("Tripwire: share · now 31% · review at below 27.9%");
  });

  it("toggles closed again, and starts collapsed on every new render (not persisted)", () => {
    const { unmount } = render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    open(/Declines reviewed/);
    expect(text()).toContain("lost share");
    open(/Declines reviewed/);
    expect(text()).not.toContain("lost share");
    open(/Declines reviewed/);
    unmount();
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).not.toContain("lost share");
  });

  it("says so when there are no declines or no threats", () => {
    hook = { data: row({ pass1: record({ observed_damage: [], forward_threats: { threat_level: "Low", threats: [] } }) }) };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(screen.getByRole("button", { name: /Declines reviewed: 0 found, 0 counted/ })).toBeInTheDocument();
    open(/Declines reviewed/);
    open(/^Forward threats/);
    expect(text()).toContain("No declines were found.");
    expect(text()).toContain("No threats were listed.");
  });
});

describe("an inconclusive check", () => {
  beforeEach(() => {
    hook = { data: inconclusive() };
  });

  it("says the passes disagree and offers no rating, no suggestion and no agrees/differs", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("passes disagree");
    expect(within(screen.getByTestId("moat-check-card")).getByText("Inconclusive")).toBeInTheDocument();
    expect(text()).not.toMatch(/Agrees|Differs|No set rating/);
    expect(text()).toContain("Low");
    expect(text()).toContain("Pass 1: High · Pass 2: Moderate");
  });

  it("shows both passes side by side with their rating, reading, strongest source and supporting item", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    const one = screen.getByRole("group", { name: "Pass 1" });
    const two = screen.getByRole("group", { name: "Pass 2" });
    expect(one.textContent).toContain("Wide moat");
    expect(one.textContent).toContain("Outcome reading: supported");
    expect(one.textContent).toContain("Strongest source: Brand");
    expect(one.textContent).toContain("share 31%");
    expect(one.textContent).toContain("Supporting item: share held at 31%");
    expect(two.textContent).toContain("Narrow moat");
    expect(two.textContent).toContain("Outcome reading: neutral");
    expect(two.textContent).toContain("Supporting item: pass two item");
  });

  it("stacks on mobile and goes two columns from md", () => {
    const { container } = render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(container.querySelector(".md\\:grid-cols-2")).not.toBeNull();
    expect(container.querySelector(".grid.gap-4")?.className).not.toMatch(/(^|\s)grid-cols-2/);
  });

  it("gives a short why-inconclusive line from the two readings", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain('Pass 1 rated Wide moat on a "supported" reading; pass 2 rated Narrow moat on a "neutral" reading.');
  });

  it("has no single-pass sections", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(text()).not.toContain("Evidence check");
    expect(text()).not.toContain("Would lower it");
  });

  it("copes with an unreadable pass record by showing its stored rating", () => {
    hook = { data: inconclusive({ pass2: "junk" }) };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(screen.getByRole("group", { name: "Pass 2" }).textContent).toContain("Narrow moat");
  });

  it("still flags company-reported proof", () => {
    hook = { data: inconclusive({ proof_basis: "company_reported_only" }) };
    render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(text()).toContain("Unverified by independent source");
  });
});

describe("plain text and links", () => {
  const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

  it("draws model-written text as text, never as markup", () => {
    hook = {
      data: row({
        pass1: record({
          narrative: hostile,
          would_lower: hostile,
          evidence_note: hostile,
          outcome_supporting_item: hostile,
          observed_damage: [{ metric: hostile, change: hostile, period: hostile, counted: "yes", reason: hostile }],
          forward_threats: { threat_level: "Low", threats: [{ name: hostile, level: "Low", observed_so_far: hostile, tripwire: { metric: hostile, value_now: hostile, review_level: hostile } }] },
          source_facts: { brand_monopoly: { fact: hostile, source: "https://example.com/a", date: hostile } },
          sources_rating: { brand_monopoly: "strong" },
        }),
      }),
    };
    const { container } = render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    open(/Fact behind each source rating/);
    open(/Declines reviewed/);
    open(/^Forward threats/);
    expect(container.querySelector("img, script, iframe, object")).toBeNull();
    expect(text()).toContain("<img src=x");
    expect(text()).toContain("<script>alert(2)</script>");
  });

  it("links only http and https sources, with the hostname as the text and rel noopener noreferrer", () => {
    hook = {
      data: row({
        pass1: record({
          sources_rating: { brand_monopoly: "strong", switching_costs: "moderate", barriers_to_entry: "weak", network_effect: "weak", economies_of_scale: "weak" },
          source_facts: {
            brand_monopoly: { fact: "a", source: "https://www.example.com/a", date: "2026-01-01" },
            switching_costs: { fact: "b", source: "javascript:alert(1)", date: "2026-01-01" },
            barriers_to_entry: { fact: "c", source: "data:text/html,<b>x</b>", date: "2026-01-01" },
            network_effect: { fact: "d", source: "/relative/path", date: "2026-01-01" },
            economies_of_scale: { fact: "e", source: "http://plain.example.net/x", date: "2026-01-01" },
          },
        }),
      }),
    };
    const { container } = render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    open(/Fact behind each source rating/);
    const facts = container.querySelectorAll("a[href]");
    const hrefs = Array.from(facts).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(expect.arrayContaining(["https://www.example.com/a", "http://plain.example.net/x"]));
    expect(hrefs.some((h) => /^(javascript|data):/i.test(h ?? "") || h === "/relative/path")).toBe(false);
    for (const a of Array.from(facts)) {
      expect(a.getAttribute("rel")).toBe("noopener noreferrer");
      expect(a.getAttribute("target")).toBe("_blank");
    }
    expect(screen.getAllByRole("link", { name: "example.com" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "plain.example.net" })).toBeInTheDocument();
    expect(text()).toContain("javascript:alert(1)"); // an unsafe source is shown as text
  });
});

describe("read-only", () => {
  it("has no Apply button, and every button is a collapsible toggle", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="narrow_moat" />);
    expect(screen.queryByRole("button", { name: /apply|save|confirm|use this|set rating/i })).toBeNull();
    for (const button of screen.getAllByRole("button")) expect(button).toHaveAttribute("aria-expanded");
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });

  it("makes no write call however much is opened", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="narrow_moat" />);
    for (const button of screen.getAllByRole("button")) fireEvent.click(button);
    expect(apiPut).not.toHaveBeenCalled();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("shows no overall-if-applied score", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="narrow_moat" />);
    expect(text()).not.toMatch(/if applied|overall score|Overall =/i);
  });

  it("uses the Moat tier words only, never a verdict word", () => {
    render(<MoatCheckCard ticker="AAPL" setRating="narrow_moat" />);
    expect(text()).not.toMatch(/\bFail\b|May not pass|Strong pass/);
  });
});

describe("design rules", () => {
  it("is sentence case: no uppercase or wide tracking, and the title is a level-3 heading", () => {
    const { container } = render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(container.innerHTML).not.toMatch(/uppercase|tracking-wide|tracking-widest/);
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Independent check");
  });

  it("wraps its pills and lets long text break rather than overflow", () => {
    const { container } = render(<MoatCheckCard ticker="AAPL" setRating="wide_moat" />);
    expect(container.querySelector(".flex.flex-wrap.gap-2")).not.toBeNull();
    expect(container.querySelector(".break-words")).not.toBeNull();
    expect(container.querySelector(".sm\\:grid-cols-3")).not.toBeNull();
  });
});
