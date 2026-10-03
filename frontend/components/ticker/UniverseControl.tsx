"use client";

import { Plus } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { errorDetail } from "@/lib/api/client";
import type { UniverseAddOut, UniverseRemoveOut, UniverseStatusOut } from "@/lib/api/types";
import { addToUniverse, removeFromUniverse, useUniverseStatus } from "@/lib/hooks/useUniverse";
import { universeAction } from "@/lib/universe";

type Phase = "idle" | "confirming" | "adding" | "removing";
type Message = { tone: "note" | "error"; text: string };

const ADDED_NO_SCORE = "Added. The score will be filled in by the nightly run.";
const ADDED_NO_CARD = "Added. The card appears after tonight's run.";

/** What to say after a successful Add, if anything: a stock whose live score did not compute (the response's own
 * message says why, e.g. the fundamentals group is off), an ETF whose card was not written. Otherwise nothing. */
function addNote(result: UniverseAddOut): string | null {
  if (result.score_computed === false) return result.message || ADDED_NO_SCORE;
  if (result.row_written === false) return ADDED_NO_CARD;
  return null;
}

interface FlowArgs {
  status: UniverseStatusOut | null | undefined;
  add: (ticker: string) => Promise<UniverseAddOut>;
  remove: (ticker: string) => Promise<UniverseRemoveOut>;
  /** A page that switches tickers without remounting passes the ticker so the flow starts clean. */
  resetKey?: string;
  // Styleguide seams (the hook-driven control passes neither): start in a given phase / with a given message.
  defaultPhase?: Phase;
  defaultMessage?: Message | null;
}

/** The universe flow, as two separate nodes so a header can put them in different places: `control` is only ever one
 * button ("Add to Universe", or "Remove from Universe" with its inline Confirm/Cancel) or null, and sits in the header's
 * action row; `note` is the success note / error line, which must NOT sit in that row (it would move the buttons), and
 * renders as a small line under the action cluster. Everything is decided from the status response (`universeAction`);
 * there is no "In universe" label. Deliberately quieter than the primary "Add to watchlist" beside it: an outline Add
 * and a ghost Remove. */
export function useUniverseFlow({ status, add, remove, resetKey, defaultPhase = "idle", defaultMessage = null }: FlowArgs): {
  control: ReactNode;
  note: ReactNode;
} {
  const [phase, setPhase] = useState<Phase>(defaultPhase);
  const [message, setMessage] = useState<Message | null>(defaultMessage);
  const [scope, setScope] = useState(resetKey);
  if (scope !== resetKey) {
    // Derived-state reset: a different ticker never inherits the previous one's pending/confirm state or message.
    setScope(resetKey);
    setPhase("idle");
    setMessage(null);
  }
  const action = universeAction(status);
  const ticker = status?.ticker ?? "";

  async function handleAdd() {
    setPhase("adding");
    setMessage(null);
    try {
      const note = addNote(await add(ticker));
      if (note) setMessage({ tone: "note", text: note });
    } catch (e) {
      // Status unchanged: the button stays and the backend's reason (400 non-US, 404, 409 delisted, 503) shows below.
      setMessage({ tone: "error", text: errorDetail(e) ?? "Couldn't add to the universe" });
    }
    setPhase("idle");
  }

  async function handleRemove() {
    setPhase("removing");
    setMessage(null);
    try {
      await remove(ticker);
    } catch (e) {
      // A 409 means a protection appeared since the page loaded; removeFromUniverse already revalidated the status.
      setMessage({ tone: "error", text: errorDetail(e) ?? "Couldn't remove from the universe" });
    }
    setPhase("idle");
  }

  let control: ReactNode = null;
  if (action === "add") {
    control = (
      <Button variant="outline" size="sm" onClick={handleAdd} disabled={phase === "adding"} className="shrink-0">
        <Plus size={12} weight="bold" aria-hidden="true" />
        {phase === "adding" ? "Adding…" : "Add to Universe"}
      </Button>
    );
  } else if (action === "remove") {
    control =
      phase === "confirming" || phase === "removing" ? (
        <div className="flex shrink-0 flex-nowrap items-center gap-2 whitespace-nowrap">
          <span className="text-xs text-negative">Remove from Universe?</span>
          <Button variant="danger" size="sm" onClick={handleRemove} disabled={phase === "removing"}>
            {phase === "removing" ? "Removing…" : "Confirm"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setPhase("idle")} disabled={phase === "removing"}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setPhase("confirming")}
          className="shrink-0 text-text-tertiary hover:text-negative"
        >
          Remove from Universe
        </Button>
      );
  }

  const note = message ? (
    <p
      role={message.tone === "error" ? "alert" : "status"}
      className={`max-w-xs text-right text-xs ${message.tone === "error" ? "text-negative" : "text-text-tertiary"}`}
    >
      {message.text}
    </p>
  ) : null;

  return { control, note };
}

/** Hook-driven: reads GET /tickers/{t}/universe (a failed or loading request yields no control and no banner) and wires
 * the real Add / Remove. The header renders `control` in its action row and `note` under the cluster. */
export function useUniverseControl(ticker: string) {
  const { data } = useUniverseStatus(ticker);
  return useUniverseFlow({ status: data, add: addToUniverse, remove: removeFromUniverse, resetKey: ticker });
}

/** Presentational stack (control above its note) for the styleguide, which draws each state from a mock status. */
export function UniverseControlView(props: FlowArgs) {
  const { control, note } = useUniverseFlow(props);
  if (!control && !note) return null;
  return (
    <div className="flex flex-col items-end gap-1">
      {control}
      {note}
    </div>
  );
}
