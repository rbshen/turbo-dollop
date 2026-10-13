"use client";

import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth/AuthProvider";

/** Renders its children for an admin and nothing (or `fallback`) for everyone else, including while the role is still being
 * fetched, so a viewer never sees an admin control flash. Use it around every control that writes (PUT / POST / PATCH / DELETE)
 * or that reads an admin-only endpoint. UX only: the backend answers 403 to a viewer's write whatever the page shows
 * (core/route_roles.py). `lib/api/adminGuard.test.tsx` fails when a component calls a write without a guard like this one. */
export function AdminOnly({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  const { isAdmin } = useAuth();
  return <>{isAdmin ? children : fallback}</>;
}
