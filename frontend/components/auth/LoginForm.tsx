"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { navigate } from "@/lib/auth/navigate";
import { DEFAULT_AFTER_LOGIN, safeNextPath } from "@/lib/auth/safeNext";

/** "about a minute" / "about N minutes" from a Retry-After in seconds; empty when the server gave none. */
function waitHint(seconds: number | undefined): string {
  if (!seconds) return "";
  const minutes = Math.ceil(seconds / 60);
  return minutes <= 1 ? " Try again in about a minute." : ` Try again in about ${minutes} minutes.`;
}

/** The only wording the form shows: never the backend's own text, so a failure says nothing about which half was wrong. */
export function loginErrorMessage(e: unknown): string {
  if (e instanceof ApiError && e.status === 401) return "Invalid username or password.";
  if (e instanceof ApiError && e.status === 429) return `Too many failed sign-in attempts.${waitHint(e.retryAfter) || " Try again later."}`;
  return "Couldn't sign in. Check your connection and try again.";
}

export function LoginForm() {
  const { user, isLoading, login } = useAuth();
  const target = safeNextPath(useSearchParams()?.get("next")) ?? DEFAULT_AFTER_LOGIN;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Signed in, whether just now or already on arrival: leave. Covers /login opened while holding a valid session.
  useEffect(() => {
    if (!isLoading && user) navigate(target);
  }, [isLoading, user, target]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await login(username.trim(), password);
      // The effect above navigates once the user is set; the button stays disabled until the page unloads.
    } catch (err) {
      setError(loginErrorMessage(err));
      setPending(false);
    }
  }

  if (isLoading || user) return null; // checking the session, or already leaving

  return (
    <PageContainer className="flex flex-1 items-start justify-center pt-24 pb-12">
      <Card className="w-full max-w-sm">
        <h1 className="font-heading text-2xl font-medium text-text-primary">Sign in</h1>
        <p className="mt-1 text-sm text-text-secondary">Fathom accounts are created by an administrator.</p>
        <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
          <FormField label="Username" htmlFor="login-username">
            <Input
              id="login-username"
              name="username"
              size="full"
              autoFocus
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </FormField>
          <FormField label="Password" htmlFor="login-password">
            <Input
              id="login-password"
              name="password"
              type="password"
              size="full"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </FormField>
          {error && (
            <p role="alert" className="text-sm text-negative">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" disabled={pending || username.trim() === "" || password === ""}>
            {pending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </PageContainer>
  );
}
