"use client";

// Save status for a Settings form, held ABOVE the form's `key={updated_at}`
// remount. A successful save changes updated_at, which replaces the keyed form
// as soon as the fresh data arrives -- state kept inside it (the old
// per-form `status`) was lost before "Saved ✓" could show. The wrapper that
// owns the SWR hook calls this once and hands the result down as `saver`.
import { useCallback, useEffect, useRef, useState } from "react";

import { errorDetail } from "@/lib/api/client";
import type { SaveStatus } from "@/components/settings/SettingsLayout";

// How long "Saved ✓" / "Save failed" stays before the status text empties.
export const SAVE_STATUS_RESET_MS = 3000;

export function useSettingsSave() {
  const [status, setStatus] = useState<SaveStatus>("idle");
  // The server's own reason for a rejected save (e.g. a 422's message), shown
  // after "Save failed"; undefined when there is none.
  const [detail, setDetail] = useState<string | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  const run = useCallback(async (action: () => Promise<void>) => {
    clearTimeout(timer.current);
    setStatus("saving");
    setDetail(undefined);
    try {
      await action();
      setStatus("saved");
    } catch (e) {
      setDetail(errorDetail(e));
      setStatus("error");
    } finally {
      timer.current = setTimeout(() => setStatus("idle"), SAVE_STATUS_RESET_MS);
    }
  }, []);

  return { status, detail, run };
}

export type SettingsSaver = ReturnType<typeof useSettingsSave>;
