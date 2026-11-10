"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/hooks/use-api";
import { AppContext } from "@/components/app/app-context";
import { ThemeToggle } from "@/components/app/theme-toggle";
import { ErrorNote, PageLoading } from "@/components/app/common";
import { Button } from "@/components/ui/button";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const me = useResource("me", () => api.me());
  const ai = useResource("ai-status", () => api.aiStatus());

  if (me.loading || !me.data) {
    return (
      <div className="flex flex-1 items-center justify-center">
        {me.error && me.error.status !== 401 ? (
          <div className="max-w-md space-y-3 p-6">
            <ErrorNote error={me.error} />
            <Button variant="outline" onClick={me.reload}>Retry</Button>
          </div>
        ) : (
          <PageLoading />
        )}
      </div>
    );
  }

  return (
    <AppContext.Provider value={{ user: me.data, ai: ai.data }}>
      <header className="sticky top-0 z-30 border-b bg-background/95">
        <div className="mx-auto flex h-12 max-w-7xl items-center justify-between gap-3 px-4">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <ShieldCheck className="size-5 text-brand" aria-hidden />
            <span className="hidden sm:inline">AI Engineering Auditor</span>
            <span className="sm:hidden">Auditor</span>
          </Link>
          <div className="flex items-center gap-1">
            <span className="hidden max-w-[16rem] truncate text-xs text-muted-foreground sm:inline">{me.data.email}</span>
            <ThemeToggle />
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                try {
                  await api.logout();
                } finally {
                  router.replace("/login");
                }
              }}
            >
              <LogOut /> <span className="hidden sm:inline">Log out</span>
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
    </AppContext.Provider>
  );
}
