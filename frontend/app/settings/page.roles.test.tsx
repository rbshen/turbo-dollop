// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import { TestAuth } from "@/lib/auth/testAuth";

// The REAL sections and hooks, with only the transport replaced: every request the page makes is recorded (and answered with an
// error, which each section handles by drawing its own message). This is what proves a viewer's Settings page never asks for an
// admin-only endpoint, i.e. never produces a 403.
const h = vi.hoisted(() => ({ requested: [] as string[], search: null as string | null }));
vi.mock("@/lib/api/client", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/client")>()),
  apiFetch: (path: string) => {
    h.requested.push(path);
    return Promise.reject(new Error("offline"));
  },
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(h.search ? { section: h.search } : {}) }));

const ADMIN_ONLY_READS = ["/config/cron-health", "/config/data-groups", "/config/data-source-health"];

beforeEach(() => {
  h.requested = [];
  h.search = null;
});
afterEach(cleanup);

function draw(role: "admin" | "viewer" | null, loading = false) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <TestAuth role={role} loading={loading}>
        <SettingsPage />
      </TestAuth>
    </SWRConfig>,
  );
}

const labels = () => screen.getAllByRole("button").map((b) => b.textContent);

describe("Settings page by role", () => {
  it("lists all eight sections for an admin, and the first one reads cron health", async () => {
    draw("admin");
    expect(labels()).toHaveLength(8);
    await waitFor(() => expect(h.requested).toContain("/config/cron-health"));
  });

  it("lists only the six viewer-readable sections for a viewer", () => {
    draw("viewer");
    expect(labels()).toEqual(["Discount rate by country", "Score weighting", "Economic moat", "REIT", "Liquidity", "Weinstein"]);
  });

  it("never requests an admin-only endpoint for a viewer, on any section", async () => {
    draw("viewer");
    for (const name of labels() as string[]) {
      fireEvent.click(screen.getByRole("button", { name }));
      await waitFor(() => expect(h.requested.length).toBeGreaterThan(0));
    }
    expect(h.requested.length).toBeGreaterThan(0);
    for (const admin of ADMIN_ONLY_READS) {
      expect(h.requested.filter((p) => p.startsWith(admin)), admin).toEqual([]);
    }
  });

  it.each(["scheduled-jobs", "fmp-data-groups"])("a viewer's deep link to %s falls back to the first visible section", async (section) => {
    h.search = section;
    draw("viewer");
    await waitFor(() => expect(h.requested.length).toBeGreaterThan(0));
    expect(h.requested.some((p) => ADMIN_ONLY_READS.some((a) => p.startsWith(a)))).toBe(false);
    expect(h.requested).toContain("/config/discount-rates");
  });

  it("fetches nothing while the role is unknown (the first section is an admin one)", () => {
    draw(null, true);
    expect(h.requested).toEqual([]);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
