// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import { TestAuth } from "@/lib/auth/testAuth";

// The REAL sections and hooks, with only the transport replaced: every request the page makes is recorded (and answered with an
// error, which each section handles by drawing its own message). This is what proves a viewer's Settings page never mounts a section,
// so it never asks for a Settings-only endpoint (which the backend would answer with 403 anyway).
const h = vi.hoisted(() => ({ requested: [] as string[], search: null as string | null, replace: vi.fn() }));
vi.mock("@/lib/api/client", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/client")>()),
  apiFetch: (path: string) => {
    h.requested.push(path);
    return Promise.reject(new Error("offline"));
  },
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(h.search ? { section: h.search } : {}),
  useRouter: () => ({ replace: h.replace }),
}));

beforeEach(() => {
  h.requested = [];
  h.search = null;
  h.replace.mockReset();
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
    expect(h.replace).not.toHaveBeenCalled();
  });

  it("sends a viewer home and mounts nothing: no heading, no section, no request", async () => {
    draw("viewer");
    await waitFor(() => expect(h.replace).toHaveBeenCalledWith("/"));
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("heading", { name: "Settings" })).toBeNull();
    expect(h.requested).toEqual([]);
  });

  it.each(["scheduled-jobs", "score-weighting", "economic-moat", "weinstein"])("a viewer's deep link to %s is redirected too", async (section) => {
    h.search = section;
    draw("viewer");
    await waitFor(() => expect(h.replace).toHaveBeenCalledWith("/"));
    expect(h.requested).toEqual([]);
  });

  it("sends a signed-out visitor home as well", async () => {
    draw(null);
    await waitFor(() => expect(h.replace).toHaveBeenCalledWith("/"));
    expect(h.requested).toEqual([]);
  });

  it("fetches nothing and does not redirect while the role is unknown", () => {
    draw(null, true);
    expect(h.requested).toEqual([]);
    expect(h.replace).not.toHaveBeenCalled();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("keeps an admin on the page when they switch sections", async () => {
    draw("admin");
    fireEvent.click(screen.getByRole("button", { name: "Weinstein" }));
    await waitFor(() => expect(h.requested).toContain("/config/weinstein"));
    expect(h.replace).not.toHaveBeenCalled();
  });
});
