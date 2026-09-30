// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Tooltip } from "@/components/ui/tooltip";

afterEach(cleanup);

describe("Tooltip", () => {
  it("shows the content on focus of the trigger", async () => {
    render(
      <Tooltip content="Trailing twelve months.">
        <span>TTM</span>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button", { name: "TTM" });
    expect(screen.queryByText("Trailing twelve months.")).not.toBeInTheDocument();

    fireEvent.focus(trigger);
    await waitFor(() => expect(screen.getByText("Trailing twelve months.")).toBeInTheDocument());
  });

  it("keeps the trigger keyboard focusable", () => {
    render(
      <Tooltip content="Trailing twelve months.">
        <span>TTM</span>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button", { name: "TTM" });
    trigger.focus();
    expect(trigger).toHaveFocus();
  });
});
