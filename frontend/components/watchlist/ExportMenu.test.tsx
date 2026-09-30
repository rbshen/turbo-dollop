// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExportMenu } from "@/components/watchlist/ExportMenu";

afterEach(cleanup);

function renderMenu(props: { disabled?: boolean } = {}) {
  const onExportTradingView = vi.fn();
  const onExportThinkorswim = vi.fn();
  render(
    <div>
      <p data-testid="outside">elsewhere</p>
      <ExportMenu {...props} onExportTradingView={onExportTradingView} onExportThinkorswim={onExportThinkorswim} />
    </div>
  );
  const trigger = screen.getByRole("button", { name: /^Export list/i });
  return { trigger, onExportTradingView, onExportThinkorswim };
}

describe("ExportMenu", () => {
  it("starts closed and announces itself as a menu trigger", () => {
    const { trigger } = renderMenu();
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens on click with the two export items", () => {
    const { trigger } = renderMenu();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem").map((el) => el.textContent)).toEqual(["TradingView (.txt)", "thinkorswim (.csv)"]);
  });

  it("closes when the trigger is clicked again", () => {
    const { trigger } = renderMenu();
    fireEvent.click(trigger);
    fireEvent.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes on Escape from the trigger and keeps focus on it", () => {
    const { trigger } = renderMenu();
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes on Escape from a menu item and returns focus to the trigger", () => {
    const { trigger } = renderMenu();
    fireEvent.click(trigger);
    const item = screen.getAllByRole("menuitem")[0];
    item.focus();
    fireEvent.keyDown(item, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes on an outside mousedown", () => {
    const { trigger } = renderMenu();
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("stays open on a mousedown inside the menu", () => {
    const { trigger } = renderMenu();
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByRole("menu"));
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("runs the TradingView export and closes", () => {
    const { trigger, onExportTradingView, onExportThinkorswim } = renderMenu();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: "TradingView (.txt)" }));
    expect(onExportTradingView).toHaveBeenCalledTimes(1);
    expect(onExportThinkorswim).not.toHaveBeenCalled();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("runs the thinkorswim export and closes", () => {
    const { trigger, onExportTradingView, onExportThinkorswim } = renderMenu();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: "thinkorswim (.csv)" }));
    expect(onExportThinkorswim).toHaveBeenCalledTimes(1);
    expect(onExportTradingView).not.toHaveBeenCalled();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("cannot be opened while disabled", () => {
    const { trigger } = renderMenu({ disabled: true });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
