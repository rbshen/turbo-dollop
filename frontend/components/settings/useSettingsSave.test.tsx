// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SAVE_STATUS_RESET_MS, useSettingsSave } from "@/components/settings/useSettingsSave";

afterEach(() => vi.useRealTimers());

describe("useSettingsSave", () => {
  it("starts idle", () => {
    const { result } = renderHook(() => useSettingsSave());
    expect(result.current.view("a")).toEqual({ status: "idle", detail: undefined });
  });

  it("goes saving, then saved, and a success resets after 3 seconds", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSettingsSave());
    let release: () => void = () => {};
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.run(() => new Promise<void>((r) => { release = r; }), "a");
    });
    expect(result.current.status).toBe("saving");
    await act(async () => { release(); await pending; });
    expect(result.current.status).toBe("saved");
    act(() => { vi.advanceTimersByTime(SAVE_STATUS_RESET_MS - 1); });
    expect(result.current.status).toBe("saved");
    act(() => { vi.advanceTimersByTime(1); });
    expect(result.current.status).toBe("idle");
  });

  it("keeps a failure, with the server's message, indefinitely", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSettingsSave());
    await act(async () => {
      await result.current.run(async () => { throw new Error("PUT /x failed: 422 - f: bad"); }, "a");
    });
    expect(result.current.view("a")).toEqual({ status: "error", detail: "f: bad" });
    act(() => { vi.advanceTimersByTime(10 * 60_000); });
    expect(result.current.view("a")).toEqual({ status: "error", detail: "f: bad" });
  });

  it("has an error with no detail when the failure carries none", async () => {
    const { result } = renderHook(() => useSettingsSave());
    await act(async () => { await result.current.run(async () => { throw new Error("PUT /x failed: 500"); }, "a"); });
    expect(result.current.view("a")).toEqual({ status: "error", detail: undefined });
  });

  it("hides a failure once the form's values differ from what failed, and shows it again if they return", async () => {
    const { result } = renderHook(() => useSettingsSave());
    await act(async () => { await result.current.run(async () => { throw new Error("PUT /x failed: 422 - f: bad"); }, "a"); });
    expect(result.current.view("b")).toEqual({ status: "idle", detail: undefined });
    expect(result.current.view("a").status).toBe("error");
  });

  it("keeps a failure when no signature is given, until the next run", async () => {
    const { result } = renderHook(() => useSettingsSave());
    await act(async () => { await result.current.run(async () => { throw new Error("PUT /x failed: 500"); }); });
    expect(result.current.view("anything").status).toBe("error");
    expect(result.current.view().status).toBe("error");
  });

  it("a new Save attempt clears the previous failure straight away", async () => {
    const { result } = renderHook(() => useSettingsSave());
    await act(async () => { await result.current.run(async () => { throw new Error("PUT /x failed: 422 - f: bad"); }, "a"); });
    let release: () => void = () => {};
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.run(() => new Promise<void>((r) => { release = r; }), "a");
    });
    expect(result.current.view("a")).toEqual({ status: "saving", detail: undefined });
    await act(async () => { release(); await pending; });
    expect(result.current.view("a").status).toBe("saved");
  });

  it("a stale success timer never wipes a newer failure", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSettingsSave());
    await act(async () => { await result.current.run(async () => {}, "a"); });
    await act(async () => { await result.current.run(async () => { throw new Error("PUT /x failed: 500"); }, "b"); });
    act(() => { vi.advanceTimersByTime(SAVE_STATUS_RESET_MS * 2); });
    expect(result.current.view("b").status).toBe("error");
  });
});
