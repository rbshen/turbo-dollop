import type { ReactNode } from "react";

import { AuthContext, type AuthState, type Me, type Role } from "@/lib/auth/AuthProvider";

/** Test helper: render children as a fixed signed-in role (or signed out / still loading) without touching the API. */
export function TestAuth({
  role,
  loading = false,
  username = "tester",
  children,
  overrides,
}: {
  role: Role | null;
  loading?: boolean;
  username?: string;
  children: ReactNode;
  overrides?: Partial<AuthState>;
}) {
  const user: Me | null = role ? { username, role } : null;
  const value: AuthState = {
    user,
    role,
    isAdmin: role === "admin",
    isLoading: loading,
    login: async () => {
      throw new Error("login not wired in TestAuth");
    },
    logout: async () => {},
    ...overrides,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
