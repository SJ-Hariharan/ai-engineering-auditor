"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useAction } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote } from "@/components/app/common";
import { ThemeToggle } from "@/components/app/theme-toggle";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [clientError, setClientError] = useState<string | null>(null);
  const submit = useAction(async () => {
    const u = mode === "login" ? await api.login(email.trim(), password) : await api.register(email.trim(), password);
    router.replace("/");
    return u;
  });
  const isLogin = mode === "login";

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex justify-end p-3">
        <ThemeToggle />
      </div>
      <div className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="w-full max-w-sm space-y-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2 font-semibold">
              <ShieldCheck className="size-5 text-brand" aria-hidden /> AI Engineering Auditor
            </div>
            <h1 className="text-xl font-semibold tracking-tight">{isLogin ? "Log in" : "Create your account"}</h1>
            <p className="text-sm text-muted-foreground">Understand what you built. Know what to fix. Ship with confidence.</p>
          </div>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              setClientError(null);
              if (!isLogin && password.length < 10) {
                setClientError("Password must be at least 10 characters.");
                return;
              }
              void submit.run();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete={isLogin ? "current-password" : "new-password"}
                required
                minLength={isLogin ? undefined : 10}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {!isLogin && <p className="text-xs text-muted-foreground">At least 10 characters.</p>}
            </div>
            <ErrorNote error={clientError ?? submit.error} />
            <Button type="submit" className="w-full" size="lg" disabled={submit.pending}>
              {submit.pending ? "Please wait…" : isLogin ? "Log in" : "Create account"}
            </Button>
          </form>
          <p className="text-sm text-muted-foreground">
            {isLogin ? "No account yet? " : "Already have an account? "}
            <Link href={isLogin ? "/register" : "/login"} className="text-brand hover:underline">
              {isLogin ? "Create one" : "Log in"}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
