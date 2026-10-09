// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExportMenu } from "@/components/watchlist/ExportMenu";

afterEach(cleanup);

function renderMenu(props: { disabled?: boolean; singleDisabled?: boolean; withMultiple?: boolean } = {}) {
  const { withMultiple, ...menuProps } = props;
  const onExportTradingView = vi.fn();
  const onExportThinkorswim = vi.fn();
  const onExportMultiple = vi.fn();
  render(
    <div>
      <p data-testid="outside">elsewhere</p>
      <ExportMenu
        {...menuProps}
        onExportTradingView={onExportTradingView}
        onExportThinkorswim={onExportThinkorswim}
        onExportMultiple={withMultiple ? onExportMultiple : undefined}
      />
    </div>
  );
  const trigger = screen.getByRole("button", { name: /^Export list/i });
  return { trigger, onExportTradingView, onExportThinkorswim, onExportMultiple };
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

  it("is a 32px outline button with a hidden caret icon and no text glyph", () => {
    const { trigger } = renderMenu();
    expect(trigger).toHaveClass("border", "border-border-input", "h-8");
    expect(trigger.textContent).toBe("Export list");
    expect(trigger.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("names the menu in sentence case", () => {
    const { trigger } = renderMenu();
    fireEvent.click(trigger);
    expect(screen.getByRole("menu", { name: "Export list" })).toBeInTheDocument();
  });

  describe("with the multi-list item", () => {
    it("adds Export multiple lists… as a third item after a separator", () => {
      const { trigger } = renderMenu({ withMultiple: true });
      fireEvent.click(trigger);
      expect(screen.getAllByRole("menuitem").map((el) => el.textContent)).toEqual([
        "TradingView (.txt)",
        "thinkorswim (.csv)",
        "Export multiple lists…",
      ]);
      expect(screen.getByRole("separator")).toBeInTheDocument();
    });

    it("runs it and closes the menu", () => {
      const { trigger, onExportMultiple, onExportTradingView } = renderMenu({ withMultiple: true });
      fireEvent.click(trigger);
      fireEvent.click(screen.getByRole("menuitem", { name: "Export multiple lists…" }));
      expect(onExportMultiple).toHaveBeenCalledTimes(1);
      expect(onExportTradingView).not.toHaveBeenCalled();
      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });

    it("keeps the multi-list item usable while the two single-list items are disabled", () => {
      const { trigger, onExportMultiple, onExportTradingView } = renderMenu({ withMultiple: true, singleDisabled: true });
      expect(trigger).toBeEnabled();
      fireEvent.click(trigger);
      expect(screen.getByRole("menuitem", { name: "TradingView (.txt)" })).toBeDisabled();
      expect(screen.getByRole("menuitem", { name: "thinkorswim (.csv)" })).toBeDisabled();
      fireEvent.click(screen.getByRole("menuitem", { name: "TradingView (.txt)" }));
      expect(onExportTradingView).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("menuitem", { name: "Export multiple lists…" }));
      expect(onExportMultiple).toHaveBeenCalledTimes(1);
    });
  });
});
