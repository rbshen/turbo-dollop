// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/auth/LoginForm";
import { ApiError } from "@/lib/api/client";
import { TestAuth } from "@/lib/auth/testAuth";

const h = vi.hoisted(() => ({ next: null as string | null, navigate: vi.fn() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(h.next === null ? {} : { next: h.next }) }));
vi.mock("@/lib/auth/session", async (orig) => ({ ...(await orig<typeof import("@/lib/auth/session")>()), navigate: h.navigate }));

afterEach(cleanup);
beforeEach(() => {
  h.next = null;
  h.navigate.mockReset();
});

function setup(login: (u: string, p: string) => Promise<unknown>, opts: { role?: "admin" | "viewer" | null; loading?: boolean } = {}) {
  const view = render(
    <TestAuth role={opts.role ?? null} loading={opts.loading} overrides={{ login: login as never }}>
      <LoginForm />
    </TestAuth>,
  );
  return view;
}

async function submit(username = "ann", password = "correct horse") {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  });
}

describe("LoginForm", () => {
  it("has a focused username, a password field and the password-manager autocomplete attributes", () => {
    setup(vi.fn());
    const user = screen.getByLabelText("Username");
    const pass = screen.getByLabelText("Password");
    expect(user).toHaveFocus();
    expect(user).toHaveAttribute("autocomplete", "username");
    expect(pass).toHaveAttribute("autocomplete", "current-password");
    expect(pass).toHaveAttribute("type", "password");
  });

  it("keeps the submit disabled until both fields are filled", () => {
    setup(vi.fn());
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "ann" } });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "x" } });
    expect(button).toBeEnabled();
  });

  it("signs in with the typed credentials and is disabled while pending", async () => {
    let resolve!: (v: unknown) => void;
    const login = vi.fn().mockReturnValue(new Promise((r) => (resolve = r)));
    setup(login);
    await submit("  ann  ", "pw pw pw pw pw");
    expect(login).toHaveBeenCalledWith("ann", "pw pw pw pw pw");
    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
    await act(async () => resolve({ username: "ann", role: "admin" }));
  });

  it("shows one generic message for a 401, never the backend's wording", async () => {
    setup(vi.fn().mockRejectedValue(new ApiError("POST /auth/login failed: 401 - Invalid credentials", 401, "Invalid credentials")));
    await submit();
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid username or password.");
    expect(screen.getByRole("alert")).not.toHaveTextContent("credentials");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled(); // can retry
  });

  it.each([
    [900, "Too many failed sign-in attempts. Try again in about 15 minutes."],
    [61, "Too many failed sign-in attempts. Try again in about 2 minutes."],
    [30, "Too many failed sign-in attempts. Try again in about a minute."],
    [undefined, "Too many failed sign-in attempts. Try again later."],
  ])("shows the 429 message with a wait hint from Retry-After %s", async (retryAfter, text) => {
    setup(vi.fn().mockRejectedValue(new ApiError("429", 429, "Too many failed sign-in attempts. Try again later.", retryAfter)));
    await submit();
    expect(screen.getByRole("alert")).toHaveTextContent(text);
  });

  it("shows a neutral message for a network failure", async () => {
    setup(vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await submit();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't sign in.");
  });

  it("goes to the default page after sign-in when there is no next", async () => {
    const { rerender } = setup(vi.fn());
    rerender(
      <TestAuth role="admin">
        <LoginForm />
      </TestAuth>,
    );
    expect(h.navigate).toHaveBeenCalledWith("/screener");
  });

  it("goes to a valid next after sign-in", () => {
    h.next = "/screener?x=1";
    setup(vi.fn(), { role: "viewer" });
    expect(h.navigate).toHaveBeenCalledWith("/screener?x=1");
  });

  it.each(["//evil.com", "http://evil.com", "/\\evil", "/login", "evil.com"])("ignores the unsafe next %s", (next) => {
    h.next = next;
    setup(vi.fn(), { role: "admin" });
    expect(h.navigate).toHaveBeenCalledTimes(1);
    expect(h.navigate).toHaveBeenCalledWith("/screener");
  });

  it("redirects away at once when already signed in, and draws no form", () => {
    setup(vi.fn(), { role: "viewer" });
    expect(h.navigate).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText("Username")).toBeNull();
  });

  it("waits for the session check before deciding, drawing nothing", () => {
    setup(vi.fn(), { role: null, loading: true });
    expect(h.navigate).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Username")).toBeNull();
  });
});
