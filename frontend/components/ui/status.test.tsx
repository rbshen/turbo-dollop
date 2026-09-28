// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Status } from "@/components/ui/status";

afterEach(cleanup);

describe("Status", () => {
  it("renders a dot for a toned status", () => {
    const { container } = render(<Status tone="positive">Pass</Status>);
    expect(container.querySelector("[aria-hidden]")).not.toBeNull();
  });

  it("renders no dot/glyph for neutral", () => {
    const { container } = render(<Status tone="neutral">Not scored</Status>);
    expect(container.querySelector("[aria-hidden]")).toBeNull();
  });

  it("renders a direction glyph instead of a dot when direction is given", () => {
    const { container } = render(
      <Status tone="negative" direction="down">
        -1.20%
      </Status>,
    );
    expect(container.querySelector("[aria-hidden]")?.textContent).toBe("▼");
  });
});
