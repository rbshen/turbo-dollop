// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RecomputeStatusLine } from "@/components/settings/RecomputeStatusLine";

const h = vi.hoisted(() => ({ status: { run: null, running: false } as { run: unknown; running: boolean } }));
vi.mock("@/lib/hooks/useScoreWeights", () => ({ useRecomputeStatus: () => h.status }));

afterEach(cleanup);

describe("RecomputeStatusLine", () => {
  const failed = (error: string | null) => ({ run: { state: "failed", error, processed: 0, total: 10, failed: 0 }, running: false });

  it("quotes the reason when there is one (admin)", () => {
    h.status = failed("FMP is down.");
    render(<RecomputeStatusLine />);
    expect(screen.getByTestId("recompute-status")).toHaveTextContent("The last score recompute failed: FMP is down.");
  });

  it("reads cleanly when a viewer's reason is redacted to null", () => {
    h.status = failed(null);
    render(<RecomputeStatusLine />);
    const text = screen.getByTestId("recompute-status").textContent ?? "";
    expect(text).toMatch(/^The last score recompute failed\. Your settings are saved/);
    expect(text).not.toMatch(/null|unknown error|undefined/);
  });
});
