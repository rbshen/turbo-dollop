// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUniverseControl } from "@/components/ticker/UniverseControl";
import type { UniverseAddOut, UniverseRemoveOut, UniverseStatusOut } from "@/lib/api/types";

let hookResult: { data: UniverseStatusOut | undefined; error?: Error };
const addToUniverse = vi.fn();
const removeFromUniverse = vi.fn();
vi.mock("@/lib/hooks/useUniverse", () => ({
  useUniverseStatus: () => hookResult,
  addToUniverse: (...a: unknown[]) => addToUniverse(...a),
  removeFromUniverse: (...a: unknown[]) => removeFromUniverse(...a),
}));

function status(over: Partial<UniverseStatusOut> = {}): UniverseStatusOut {
  return {
    ticker: "ABC",
    kind: "stock",
    in_universe: false,
    classification: "browsed",
    state: "browsed",
    reasons: [],
    can_add: true,
    can_remove: false,
    added_at: null,
    added_source: null,
    delisted: false,
    ...over,
  };
}
const ADDED: Partial<UniverseStatusOut> = { state: "added", can_add: false, can_remove: true, in_universe: true, classification: "added" };
const PROTECTED: Partial<UniverseStatusOut> = { state: "protected", can_add: false, in_universe: true, classification: "index", reasons: ["index:sp500", "watchlist:E3"] };

function addOut(over: Partial<UniverseAddOut> = {}): UniverseAddOut {
  return { status: status(ADDED), changed: true, score_computed: true, row_written: null, reason: null, error: null, fmp_calls: null, message: "Added ABC and computed its score.", ...over };
}
function removeOut(): UniverseRemoveOut {
  return { status: status(), changed: true, message: "Removed ABC from the universe." };
}

beforeEach(() => {
  hookResult = { data: status() };
  addToUniverse.mockReset().mockResolvedValue(addOut());
  removeFromUniverse.mockReset().mockResolvedValue(removeOut());
});
afterEach(cleanup);

// A stand-in header: the control goes in the action row, the note in its own line under the row, exactly as the real
// headers place them.
function Harness({ ticker }: { ticker: string }) {
  const { control, note } = useUniverseControl(ticker);
  return (
    <div>
      <div data-testid="row">{control}</div>
      <div data-testid="note">{note}</div>
    </div>
  );
}

function renderControl() {
  return render(<Harness ticker="ABC" />);
}

describe("display rules", () => {
  it("browsed + can_add: only an outline 'Add to Universe' button, quieter than the primary watchlist button", () => {
    renderControl();
    const button = screen.getByRole("button", { name: "Add to Universe" });
    expect(button).not.toHaveClass("bg-brand");
    expect(button).toHaveClass("border");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByText(/in universe/i)).not.toBeInTheDocument();
  });

  it("added + can_remove: only the 'Remove from Universe' button, no 'In universe' label", () => {
    hookResult = { data: status(ADDED) };
    renderControl();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Remove from Universe" })).toBeInTheDocument();
    expect(screen.queryByText(/in universe/i)).not.toBeInTheDocument();
  });

  it.each([
    ["protected (index and watchlist reasons)", status(PROTECTED)],
    ["protected and added", status({ ...PROTECTED, added_at: "2026-10-03T00:00:00Z", added_source: "user" })],
    ["protected with in_universe false (Moat-only, no profile)", status({ state: "protected", can_add: false, in_universe: false, classification: null, reasons: ["manual:moat"] })],
    ["an unadmitted index name", status({ state: "protected", can_add: false, in_universe: false, reasons: ["index:russell"] })],
    ["delisted browsed", status({ delisted: true, can_add: false, classification: "delisted" })],
    ["delisted and protected", status({ delisted: true, state: "protected", can_add: false, reasons: ["index:sp500"] })],
    ["non-US (browsed, can_add false)", status({ can_add: false })],
    ["kind null", status({ kind: null })],
  ])("renders nothing for %s", (_name, s) => {
    hookResult = { data: s };
    const { container } = renderControl();
    expect(screen.getByTestId("row")).toBeEmptyDOMElement();
    expect(screen.getByTestId("note")).toBeEmptyDOMElement();
    expect(container).not.toHaveTextContent(/universe/i);
  });

  it("renders nothing while loading and after a failed status request (no error banner)", () => {
    hookResult = { data: undefined };
    const { rerender } = renderControl();
    expect(screen.getByTestId("row")).toBeEmptyDOMElement();
    hookResult = { data: undefined, error: new Error("GET /tickers/ABC/universe failed: 500") };
    rerender(<Harness ticker="ABC" />);
    expect(screen.getByTestId("row")).toBeEmptyDOMElement();
    expect(screen.getByTestId("note")).toBeEmptyDOMElement();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("notes and errors", () => {
  it("render in the note line, never inside the action row, and the button stays put", async () => {
    addToUniverse.mockResolvedValue(addOut({ score_computed: false, message: "Added ABC, but the score is pending." }));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    const note = await screen.findByRole("status");
    expect(screen.getByTestId("note")).toContainElement(note);
    expect(screen.getByTestId("row")).not.toContainElement(note);
  });

  it("an error also renders in the note line, not in the row", async () => {
    addToUniverse.mockRejectedValue(new Error("POST /tickers/ABC/universe failed: 400 - ABC is not US-listed."));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    const alert = await screen.findByRole("alert");
    expect(screen.getByTestId("note")).toContainElement(alert);
    expect(screen.getByTestId("row")).not.toContainElement(alert);
    expect(screen.getByTestId("row")).toHaveTextContent("Add to Universe");
  });

  it("the Remove 409 message renders in the note line", async () => {
    hookResult = { data: status(ADDED) };
    removeFromUniverse.mockRejectedValue(new Error("DELETE /tickers/ABC/universe failed: 409 - ABC cannot be removed."));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Remove from Universe" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    const alert = await screen.findByRole("alert");
    expect(screen.getByTestId("note")).toContainElement(alert);
    expect(screen.getByTestId("row")).not.toContainElement(alert);
  });

  it("switching ticker clears a leftover message", async () => {
    addToUniverse.mockRejectedValue(new Error("POST failed: 503 - group off"));
    const { rerender } = renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    await screen.findByRole("alert");
    hookResult = { data: status({ ticker: "XYZ" }) };
    rerender(<Harness ticker="XYZ" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Add flow", () => {
  it("calls the add helper, is disabled and says 'Adding…' while pending, and the rest of the page is not blocked", async () => {
    let resolve: (v: UniverseAddOut) => void = () => {};
    addToUniverse.mockReturnValue(new Promise<UniverseAddOut>((r) => (resolve = r)));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));

    expect(await screen.findByRole("button", { name: "Adding…" })).toBeDisabled();
    expect(addToUniverse).toHaveBeenCalledWith("ABC");
    resolve(addOut());
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to Universe" })).toBeEnabled());
  });

  it("stock, score computed: no extra note", async () => {
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    await waitFor(() => expect(addToUniverse).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to Universe" })).toBeEnabled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("stock, score_computed false: a one-line note, from the response's message", async () => {
    addToUniverse.mockResolvedValue(addOut({ score_computed: false, reason: "failed", message: "Added ABC, but computing its score failed; the nightly recompute fills it." }));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Added ABC, but computing its score failed; the nightly recompute fills it.");
  });

  it("stock, score_computed false with an empty message: the fixed fallback line", async () => {
    addToUniverse.mockResolvedValue(addOut({ score_computed: false, message: "" }));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Added. The score will be filled in by the nightly run.");
  });

  it("ETF, row_written false: 'Added. The card appears after tonight's run.'", async () => {
    hookResult = { data: status({ ticker: "QQQ", kind: "etf" }) };
    addToUniverse.mockResolvedValue(addOut({ score_computed: null, row_written: false, reason: "no_data", message: "x" }));
    render(<Harness ticker="QQQ" />);
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Added. The card appears after tonight's run.");
    expect(addToUniverse).toHaveBeenCalledWith("QQQ");
  });

  it("ETF, row_written true: no extra note", async () => {
    hookResult = { data: status({ ticker: "QQQ", kind: "etf" }) };
    addToUniverse.mockResolvedValue(addOut({ score_computed: null, row_written: true }));
    render(<Harness ticker="QQQ" />);
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    await waitFor(() => expect(addToUniverse).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to Universe" })).toBeEnabled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it.each([
    [400, "ABC is not US-listed."],
    [404, "No profile found for ABC."],
    [409, "ABC is delisted and cannot be added."],
    [503, "The profile data group is off and nothing is cached for ABC."],
  ])("HTTP %i: shows the plain detail inline, keeps the button and the status", async (code, detail) => {
    addToUniverse.mockRejectedValue(new Error(`POST /tickers/ABC/universe failed: ${code} - ${detail}`));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    expect(screen.getByRole("button", { name: "Add to Universe" })).toBeEnabled();
  });

  it("an error with no detail (network) falls back to a generic line", async () => {
    addToUniverse.mockRejectedValue(new TypeError("Failed to fetch"));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't add to the universe");
  });

  it("a new attempt clears the previous error", async () => {
    addToUniverse.mockRejectedValueOnce(new Error("POST failed: 503 - group off"));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Add to Universe" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});

describe("Remove flow", () => {
  beforeEach(() => {
    hookResult = { data: status(ADDED) };
  });

  it("is two-step and inline: Remove asks, Cancel backs out without a request", () => {
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Remove from Universe" }));
    expect(screen.getByText("Remove from Universe?")).toBeInTheDocument();
    expect(removeFromUniverse).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Remove from Universe" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(removeFromUniverse).not.toHaveBeenCalled();
  });

  it("Confirm calls the remove helper and shows a pending state", async () => {
    let resolve: (v: UniverseRemoveOut) => void = () => {};
    removeFromUniverse.mockReturnValue(new Promise<UniverseRemoveOut>((r) => (resolve = r)));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Remove from Universe" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("button", { name: "Removing…" })).toBeDisabled();
    expect(removeFromUniverse).toHaveBeenCalledWith("ABC");
    resolve(removeOut());
    await waitFor(() => expect(screen.queryByRole("button", { name: "Removing…" })).not.toBeInTheDocument());
  });

  it("a 409 shows the message, leaves the confirm, and the helper has revalidated the status", async () => {
    removeFromUniverse.mockRejectedValue(new Error("DELETE /tickers/ABC/universe failed: 409 - ABC cannot be removed: it is in the universe through watchlist:E3."));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: "Remove from Universe" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("it is in the universe through watchlist:E3");
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("once the status says browsed again, the Add button is back", () => {
    const { rerender } = renderControl();
    hookResult = { data: status() };
    rerender(<Harness ticker="ABC" />);
    expect(screen.getByRole("button", { name: "Add to Universe" })).toBeInTheDocument();
  });
});
