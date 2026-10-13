import { vi } from "vitest";

import type { AuthState, Role } from "@/lib/auth/AuthProvider";

/** For a test file about a component that is not mainly about roles but contains an admin control:
 *
 *     vi.mock("@/lib/auth/AuthProvider", async () => (await import("@/lib/auth/adminAuthMock")).adminAuthModule());
 *
 * `useAuth()` then answers a signed-in admin and the rest of the module is the real one. A test that needs the viewer's view
 * calls `setMockRole("viewer")` (and `setMockRole("admin")` in an afterEach). The dynamic import keeps this file out of the hoisted
 * factory's reach, and this file must not import the real AuthProvider as a value: it is the module being mocked. */
const current: { role: Role | null } = { role: "admin" };

export function setMockRole(role: Role | null): void {
  current.role = role;
}

export async function adminAuthModule() {
  const actual = await vi.importActual<typeof import("@/lib/auth/AuthProvider")>("@/lib/auth/AuthProvider");
  return {
    ...actual,
    useAuth: (): AuthState => ({
      user: current.role ? { username: "tester", role: current.role } : null,
      role: current.role,
      isAdmin: current.role === "admin",
      isLoading: false,
      login: async () => ({ username: "tester", role: current.role ?? "viewer" }),
      logout: async () => {},
    }),
  };
}
