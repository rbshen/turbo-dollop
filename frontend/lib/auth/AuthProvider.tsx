"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSWRConfig } from "swr";

import { apiFetch, apiPost } from "@/lib/api/client";
import { clearClientCache, navigate } from "@/lib/auth/session";

export type Role = "admin" | "viewer";

/** `GET /api/auth/me` and the answer of `POST /api/auth/login`. */
export interface Me {
  username: string;
  role: Role;
}

export interface AuthState {
  user: Me | null;
  role: Role | null;
  /** Only an admin sees a control that writes (the backend refuses a viewer's write with 403 whatever the UI shows). */
  isAdmin: boolean;
  /** True until the first `/auth/me` answer is in: nothing role-dependent should render, or a viewer would see admin controls flash. */
  isLoading: boolean;
  /** Rejects with the client's error (401 wrong credentials, 429 throttled); the caller shows it. */
  login: (username: string, password: string) => Promise<Me>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const { mutate } = useSWRConfig();

  useEffect(() => {
    let cancelled = false;
    apiFetch<Me>("/auth/me")
      .then((me) => !cancelled && setUser(me))
      .catch(() => !cancelled && setUser(null)) // 401 = signed out; any other failure also shows no controls
      .finally(() => !cancelled && setIsLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const me = await apiPost<Me>("/auth/login", { username, password });
    await clearClientCache(mutate);
    setUser(me);
    return me;
  }, [mutate]);

  const logout = useCallback(async () => {
    try {
      await apiPost("/auth/logout");
    } catch {
      // The session may already be gone (401) or the backend down: either way this browser signs out locally.
    }
    await clearClientCache(mutate);
    setUser(null);
    navigate("/login");
  }, [mutate]);

  const value = useMemo<AuthState>(
    () => ({ user, role: user?.role ?? null, isAdmin: user?.role === "admin", isLoading, login, logout }),
    [user, isLoading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
