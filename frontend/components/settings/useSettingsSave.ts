"use client";

// Save status for a Settings form, held ABOVE the form's `key={updated_at}`
// remount. A successful save changes updated_at, which replaces the keyed form
// as soon as the fresh data arrives -- state kept inside it (the old
// per-form `status`) was lost before "Saved ✓" could show. The wrapper that
// owns the SWR hook calls this once and hands the result down as `saver`.
//
// A success ("Saved ✓") resets after SAVE_STATUS_RESET_MS. A failure does NOT
// time out: its message (including a 422's reason) stays until the user's next
// edit or the next Save attempt, so it is never gone before it can be read.
// The hook cannot see edits, so the form gives it a `signature` of its field
// values with `run`, and reads the status back through `view(signature)`,
// which hides a failure once the values have changed since it happened.
import { useCallback, useEffect, useRef, useState } from "react";

import { errorDetail } from "@/lib/api/client";
import type { SaveStatus } from "@/components/settings/SettingsLayout";

// How long "Saved ✓" stays before the status text empties.
export const SAVE_STATUS_RESET_MS = 3000;

export function useSettingsSave() {
  const [status, setStatus] = useState<SaveStatus>("idle");
  // The server's own reason for a rejected save (e.g. a 422's message), shown
  // after "Save failed"; undefined when there is none.
  const [detail, setDetail] = useState<string | undefined>(undefined);
  // The form's field values when the save failed.
  const [errorSignature, setErrorSignature] = useState<string | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  const run = useCallback(async (action: () => Promise<void>, signature?: string) => {
    clearTimeout(timer.current);
    setStatus("saving");
    setDetail(undefined);
    setErrorSignature(undefined);
    try {
      await action();
      setStatus("saved");
      timer.current = setTimeout(() => setStatus("idle"), SAVE_STATUS_RESET_MS);
    } catch (e) {
      setDetail(errorDetail(e));
      setErrorSignature(signature);
      setStatus("error");
    }
  }, []);

  /** The status to show for a form whose current field values are `signature`:
   * a failure is hidden once they differ from what failed. */
  function view(signature?: string): { status: SaveStatus; detail: string | undefined } {
    const edited = status === "error" && signature !== undefined && errorSignature !== undefined && errorSignature !== signature;
    return edited ? { status: "idle", detail: undefined } : { status, detail };
  }

  return { status, detail, run, view };
}

export type SettingsSaver = ReturnType<typeof useSettingsSave>;
