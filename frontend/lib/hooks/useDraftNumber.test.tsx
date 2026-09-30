// @vitest-environment jsdom
import { createRef, type MutableRefObject } from "react";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useDraftNumber } from "@/lib/hooks/useDraftNumber";

function setup(initial: { value: number | null; owner: object }, extra: { min?: number; suffixes?: Record<string, number> } = {}) {
  const lastEmitted = createRef<unknown>() as MutableRefObject<unknown>;
  lastEmitted.current = initial.owner;
  const hook = renderHook((props: { value: number | null; owner: object }) => useDraftNumber({ ...props, lastEmitted, ...extra }), {
    initialProps: initial,
  });
  return { hook, lastEmitted };
}

describe("useDraftNumber", () => {
  it("starts from the formatted committed value", () => {
    const { hook } = setup({ value: 70, owner: {} });
    expect(hook.result.current.draft).toBe("70");
    const big = setup({ value: 1e9, owner: {} }, { suffixes: { M: 1e6, B: 1e9, T: 1e12 } });
    expect(big.hook.result.current.draft).toBe("1B");
    expect(setup({ value: null, owner: {} }).hook.result.current.draft).toBe("");
  });

  it("returns an emit outcome for valid text, null for invalid text, and no emit for a prefix", () => {
    const { hook } = setup({ value: null, owner: {} });
    let outcome;
    act(() => {
      outcome = hook.result.current.change("12.");
    });
    expect(outcome).toEqual({ emit: true, value: 12 });
    act(() => {
      outcome = hook.result.current.change("1x");
    });
    expect(outcome).toEqual({ emit: true, value: null });
    expect(hook.result.current.error).toBe("Enter a number.");
    act(() => {
      outcome = hook.result.current.change("-");
    });
    expect(outcome).toEqual({ emit: false });
    expect(hook.result.current.error).toBeNull();
  });

  it("blurring a held prefix emits null and shows the error; blurring valid text does nothing", () => {
    const { hook } = setup({ value: 5, owner: {} });
    act(() => {
      hook.result.current.change("-");
    });
    let outcome;
    act(() => {
      outcome = hook.result.current.blur();
    });
    expect(outcome).toEqual({ emit: true, value: null });
    expect(hook.result.current.error).toBe("Enter a number.");
    act(() => {
      hook.result.current.change("4");
    });
    act(() => {
      outcome = hook.result.current.blur();
    });
    expect(outcome).toEqual({ emit: false });
  });

  it("re-syncs only when the owner is a different object than the one last emitted", () => {
    const first = {};
    const { hook, lastEmitted } = setup({ value: null, owner: first });
    act(() => {
      hook.result.current.change("12.");
    });
    const emitted = {};
    lastEmitted.current = emitted;
    hook.rerender({ value: 12, owner: emitted });
    expect(hook.result.current.draft).toBe("12.");
    hook.rerender({ value: 12, owner: {} });
    expect(hook.result.current.draft).toBe("12");
  });
});
