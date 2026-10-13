// @vitest-environment jsdom
import { cleanup, render, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GroupOffBadge } from "@/components/shared/GroupOffBadge";
import { TestAuth } from "@/lib/auth/testAuth";

const h = vi.hoisted(() => ({ requested: [] as string[] }));
vi.mock("@/lib/api/client", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/client")>()),
  apiFetch: (path: string) => {
    h.requested.push(path);
    return Promise.resolve({ groups: [], tiers: [] });
  },
}));

beforeEach(() => {
  h.requested = [];
});
afterEach(cleanup);

const as = (role: "admin" | "viewer", ui: React.ReactNode) =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <TestAuth role={role}>{ui}</TestAuth>
    </SWRConfig>,
  );

describe("the data-groups badge, drawn on every ticker tab", () => {
  it("never requests /config/data-groups (admin-only, a 403) for a viewer", async () => {
    as("viewer", <GroupOffBadge groups={["fundamentals"]} />);
    await new Promise((r) => setTimeout(r, 30));
    expect(h.requested).toEqual([]);
  });

  it("does request it for an admin", async () => {
    as("admin", <GroupOffBadge groups={["fundamentals"]} />);
    await waitFor(() => expect(h.requested).toContain("/config/data-groups"));
  });
});

