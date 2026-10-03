"use client";

import { Plus } from "@phosphor-icons/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { errorDetail } from "@/lib/api/client";
import type { UniverseAddOut, UniverseRemoveOut, UniverseStatusOut } from "@/lib/api/types";
import { addToUniverse, removeFromUniverse, useUniverseStatus } from "@/lib/hooks/useUniverse";
import { universeDisplay, universeReasonsText } from "@/lib/universe";

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

interface ViewProps {
  status: UniverseStatusOut | null | undefined;
  add: (ticker: string) => Promise<UniverseAddOut>;
  remove: (ticker: string) => Promise<UniverseRemoveOut>;
  // Styleguide seams (the hook-driven control passes neither): start in a given phase / with a given message.
  defaultPhase?: Phase;
  defaultMessage?: Message | null;
}

/** The universe control on a ticker header (stock and ETF alike). Everything it shows comes from the status response
 * (`universeDisplay`): an Add button, "In universe" + an inline-confirmed Remove, a quiet protected label, or nothing
 * (no status, kind unknown, delisted, non-US, not actually in the universe). It is deliberately quieter than the
 * primary "Add to watchlist" button beside it: an outline Add, a ghost Remove, plain tertiary text for labels. */
export function UniverseControlView({ status, add, remove, defaultPhase = "idle", defaultMessage = null }: ViewProps) {
  const [phase, setPhase] = useState<Phase>(defaultPhase);
  const [message, setMessage] = useState<Message | null>(defaultMessage);
  const display = universeDisplay(status);
  const ticker = status?.ticker ?? "";

  if (!display && !message) return null;

  async function handleAdd() {
    setPhase("adding");
    setMessage(null);
    try {
      const note = addNote(await add(ticker));
      if (note) setMessage({ tone: "note", text: note });
    } catch (e) {
      // Status unchanged: the button stays and the backend's reason (400 non-US, 404, 409 delisted, 503) shows beside it.
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

  return (
    <div className="flex flex-col items-end gap-1">
      {display?.mode === "add" && (
        <Button variant="outline" size="sm" onClick={handleAdd} disabled={phase === "adding"}>
          <Plus size={12} weight="bold" aria-hidden="true" />
          {phase === "adding" ? "Adding…" : "Add to Universe"}
        </Button>
      )}
      {display?.mode === "remove" && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="text-xs text-text-tertiary">In universe</span>
          {phase === "confirming" || phase === "removing" ? (
            <>
              <span className="text-xs text-negative">Remove from Universe?</span>
              <Button variant="danger" size="sm" onClick={handleRemove} disabled={phase === "removing"}>
                {phase === "removing" ? "Removing…" : "Confirm"}
              </Button>
              <Button variant="outline" size="sm" onClick={() => setPhase("idle")} disabled={phase === "removing"}>
                Cancel
              </Button>
            </>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPhase("confirming")}
              className="text-text-tertiary hover:text-negative"
            >
              Remove from Universe
            </Button>
          )}
        </div>
      )}
      {display?.mode === "protected" && (
        <span className="text-xs text-text-tertiary" title={`In the universe through: ${universeReasonsText(display.reasons)}`}>
          In universe{display.reasons.length > 0 && <> · {universeReasonsText(display.reasons)}</>}
        </span>
      )}
      {message && (
        <p
          role={message.tone === "error" ? "alert" : "status"}
          className={`max-w-xs text-right text-xs ${message.tone === "error" ? "text-negative" : "text-text-tertiary"}`}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}

/** Hook-driven: reads GET /tickers/{t}/universe (a failed or loading request renders nothing, no error banner) and
 * wires the real Add / Remove. Key it by ticker so a page that switches tickers starts clean. */
export function UniverseControl({ ticker }: { ticker: string }) {
  const { data } = useUniverseStatus(ticker);
  return <UniverseControlView status={data} add={addToUniverse} remove={removeFromUniverse} />;
}
