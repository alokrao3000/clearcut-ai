"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Clapperboard, LogOut, Settings } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/hooks/use-clearcut";
import { ApiError, api } from "@/lib/api";
import { getServerSnapshot, getSnapshot, setToken, subscribe } from "@/lib/auth-store";
import { ROLE_LABEL } from "@/lib/labels";

/** Re-renders when the stored token changes, without putting the token in React state. */
function useToken() {
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const token = useToken();
  const { data: me, isLoading, isError } = useMe(Boolean(token));

  // `token` is null during the server render and on the first client paint, so the sign-in
  // screen is what unauthenticated visitors see without a flash of the app behind it.
  if (!token) return <SignIn />;
  if (isLoading) {
    return (
      <div className="mx-auto w-full max-w-5xl p-6">
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (isError || !me) return <SignIn />;
  return <>{children}</>;
}

export function AccountMenu() {
  const token = useToken();
  const { data: me } = useMe(Boolean(token));
  const qc = useQueryClient();

  if (!me) return null;

  const signOut = async () => {
    try {
      await api.logout();
    } catch {
      // The session may already be gone server-side; clearing locally is the point.
    }
    setToken(null);
    qc.clear();
  };

  return (
    <div className="flex items-center gap-3">
      <div className="hidden text-right sm:block">
        <div className="text-xs font-medium leading-tight">{me.user.name}</div>
        <div className="text-[11px] leading-tight text-muted-foreground">
          {me.organization.name} · {ROLE_LABEL[me.user.role]}
        </div>
      </div>
      <Button variant="ghost" size="sm" className="text-muted-foreground" asChild>
        <Link href="/settings" aria-label="Organization settings">
          <Settings />
        </Link>
      </Button>
      <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={signOut}>
        <LogOut /> <span className="sr-only sm:not-sr-only">Sign out</span>
      </Button>
    </div>
  );
}

function SignIn() {
  const [mode, setMode] = React.useState<"login" | "register">("login");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const qc = useQueryClient();

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      const result =
        mode === "login"
          ? await api.login({
              email: String(form.get("email")),
              password: String(form.get("password")),
            })
          : await api.register({
              organization_name: String(form.get("organization_name")),
              name: String(form.get("name")),
              email: String(form.get("email")),
              password: String(form.get("password")),
            });
      qc.clear();
      setToken(result.access_token);
      toast.success(mode === "login" ? "Signed in" : "Organization created");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex min-h-[80vh] items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardContent className="flex flex-col gap-5 p-6">
          <div className="flex flex-col gap-1">
            <Clapperboard className="size-6" />
            <h1 className="text-lg font-semibold tracking-tight">ClearCut AI</h1>
            <p className="text-xs text-muted-foreground">
              {mode === "login"
                ? "Sign in to your organization."
                : "Create an organization. You will be its owner."}
            </p>
          </div>

          <form className="flex flex-col gap-3" onSubmit={submit}>
            {mode === "register" && (
              <>
                <Field id="organization_name" label="Organization" autoComplete="organization" />
                <Field id="name" label="Your name" autoComplete="name" />
              </>
            )}
            <Field id="email" label="Email" type="email" autoComplete="username" />
            <Field
              id="password"
              label="Password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              hint={mode === "register" ? "At least 12 characters." : undefined}
            />

            {error && (
              <p className="text-xs text-rose-700 dark:text-rose-400" role="alert">
                {error}
              </p>
            )}

            <Button type="submit" disabled={pending}>
              {pending ? "…" : mode === "login" ? "Sign in" : "Create organization"}
            </Button>
          </form>

          <button
            type="button"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
            }}
          >
            {mode === "login"
              ? "No account? Create an organization"
              : "Already have an account? Sign in"}
          </button>

          <p className="text-[11px] leading-snug text-muted-foreground">
            Advisory drafts only — ClearCut does not provide legal clearance.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function Field({
  id,
  label,
  type = "text",
  autoComplete,
  hint,
}: {
  id: string;
  label: string;
  type?: string;
  autoComplete?: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} name={id} type={type} autoComplete={autoComplete} required />
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}
