"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { StuckCheckSettingsOut } from "@/lib/api/types";

export const STUCK_CHECK_SETTINGS_URL = "/config/stuck-check";

export function useStuckCheckSettings() {
  return useApiResource<StuckCheckSettingsOut>(STUCK_CHECK_SETTINGS_URL);
}
