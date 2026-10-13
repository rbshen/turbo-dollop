"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { StyleguideContent } from "@/app/styleguide/StyleguideContent";
import { useAuth } from "@/lib/auth/AuthProvider";

// Internal reference page: admin only. Anyone else is sent home, and the page (with everything it imports) is never mounted
// for them. UX only: the page holds no data, only the design system's own components with mock props.
export default function StyleguidePage() {
  const { isAdmin, isLoading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!isLoading && !isAdmin) router.replace("/");
  }, [isLoading, isAdmin, router]);

  if (isLoading || !isAdmin) return null;
  return <StyleguideContent />;
}
