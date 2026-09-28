// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";

afterEach(cleanup);

function renderRow(interactive?: boolean) {
  return render(
    <Table>
      <TableBody>
        <TableRow interactive={interactive} data-testid="row">
          <TableCell>AAPL</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );
}

describe("TableRow", () => {
  it("has no hover class by default", () => {
    renderRow();
    expect(screen.getByTestId("row")).not.toHaveClass("hover:bg-surface");
    expect(screen.getByTestId("row")).not.toHaveClass("cursor-pointer");
  });

  it("gets the hover and pointer classes when interactive", () => {
    renderRow(true);
    expect(screen.getByTestId("row")).toHaveClass("hover:bg-surface");
    expect(screen.getByTestId("row")).toHaveClass("cursor-pointer");
  });

  it("defaults to the 44px row height with a hairline bottom border", () => {
    renderRow();
    expect(screen.getByTestId("row")).toHaveClass("h-11", "border-b", "border-border-subtle");
  });
});
