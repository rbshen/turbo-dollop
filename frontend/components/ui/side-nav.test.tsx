// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SideNav } from "@/components/ui/side-nav";

afterEach(cleanup);

const items = [
  { href: "/settings", label: "Status" },
  { href: "/settings/liquidity-zones", label: "Liquidity Zones", current: true },
  { href: "/settings/weinstein", label: "Weinstein" },
];

describe("SideNav", () => {
  it("marks only the current item with aria-current=page", () => {
    render(<SideNav items={items} />);
    expect(screen.getByRole("link", { name: "Liquidity Zones" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Status" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Weinstein" })).not.toHaveAttribute("aria-current");
  });
});
