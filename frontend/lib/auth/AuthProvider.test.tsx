// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth, type AuthState } from "@/lib/auth/AuthProvider";

const h = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiPost: vi.fn(),
  navigate: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({ apiFetch: h.apiFetch, apiPost: h.apiPost }));
vi.mock("@/lib/auth/navigate", () => ({ navigate: h.navigate }));

const seen = { auth: null as unknown as AuthState };
function Probe() {
  const auth = useAuth();
  useEffect(() => {
    seen.auth = auth;
  });
  return <p>{auth.isLoading ? "loading" : auth.user ? `${auth.user.username}:${auth.role}:${auth.isAdmin}` : "signed out"}</p>;
}

function mount(cache = new Map()) {
  return render(
    <SWRConfig value={{ provider: () => cache }}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </SWRConfig>,
  );
}

beforeEach(() => {
  h.apiFetch.mockReset();
  h.apiPost.mockReset();
  h.navigate.mockReset();
});
afterEach(cleanup);

describe("AuthProvider", () => {
  it("is loading until /auth/me answers", async () => {
    let resolve!: (v: unknown) => void;
    h.apiFetch.mockReturnValue(new Promise((r) => (resolve = r)));
    mount();
    expect(screen.getByText("loading")).toBeInTheDocument();
    expect(seen.auth.isAdmin).toBe(false);
    await act(async () => resolve({ username: "ann", role: "admin" }));
    expect(screen.getByText("ann:admin:true")).toBeInTheDocument();
    expect(h.apiFetch).toHaveBeenCalledWith("/auth/me");
  });

  it("reports a viewer as not admin", async () => {
    h.apiFetch.mockResolvedValue({ username: "bob", role: "viewer" });
    mount();
    expect(await screen.findByText("bob:viewer:false")).toBeInTheDocument();
  });

  it("is signed out when /auth/me fails", async () => {
    h.apiFetch.mockRejectedValue(new Error("GET /auth/me failed: 401"));
    mount();
    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(seen.auth.isAdmin).toBe(false);
    expect(seen.auth.role).toBeNull();
  });

  it("login posts the credentials, stores the user and clears the SWR cache", async () => {
    h.apiFetch.mockRejectedValue(new Error("401"));
    h.apiPost.mockResolvedValue({ username: "ann", role: "admin" });
    const cache = new Map();
    cache.set("/screener", { data: [1] });
    mount(cache);
    await screen.findByText("signed out");
    await act(async () => {
      await seen.auth.login("ann", "pw");
    });
    expect(h.apiPost).toHaveBeenCalledWith("/auth/login", { username: "ann", password: "pw" });
    expect(screen.getByText("ann:admin:true")).toBeInTheDocument();
    expect(cache.get("/screener")?.data).toBeUndefined();
  });

  it("a failed login leaves the user signed out and rethrows for the form", async () => {
    h.apiFetch.mockRejectedValue(new Error("401"));
    h.apiPost.mockRejectedValue(new Error("POST /auth/login failed: 401 - Invalid credentials"));
    mount();
    await screen.findByText("signed out");
    await act(async () => {
      await expect(seen.auth.login("ann", "bad")).rejects.toThrow("Invalid credentials");
    });
    expect(screen.getByText("signed out")).toBeInTheDocument();
  });

  it("logout posts, clears the SWR cache, drops the user and goes to /login", async () => {
    h.apiFetch.mockResolvedValue({ username: "ann", role: "admin" });
    h.apiPost.mockResolvedValue(undefined);
    const cache = new Map();
    mount(cache);
    await screen.findByText("ann:admin:true");
    cache.set("/watchlists", { data: [1] });
    await act(async () => {
      await seen.auth.logout();
    });
    expect(h.apiPost).toHaveBeenCalledWith("/auth/logout");
    expect(cache.get("/watchlists")?.data).toBeUndefined();
    expect(screen.getByText("signed out")).toBeInTheDocument();
    expect(h.navigate).toHaveBeenCalledWith("/login");
  });

  it("logout still signs out locally when the POST fails", async () => {
    h.apiFetch.mockResolvedValue({ username: "ann", role: "viewer" });
    h.apiPost.mockRejectedValue(new Error("POST /auth/logout failed: 401"));
    mount();
    await screen.findByText("ann:viewer:false");
    await act(async () => {
      await seen.auth.logout();
    });
    await waitFor(() => expect(screen.getByText("signed out")).toBeInTheDocument());
    expect(h.navigate).toHaveBeenCalledWith("/login");
  });

  it("useAuth outside the provider is a loud error", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/AuthProvider/);
    spy.mockRestore();
  });
});

