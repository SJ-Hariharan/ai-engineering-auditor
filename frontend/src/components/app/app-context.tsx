"use client";

import { createContext, useContext } from "react";
import type { AIStatus, User } from "@/lib/types";

export interface AppCtx {
  user: User;
  /** null when the status call failed. */
  ai: AIStatus | null;
}
export const AppContext = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const v = useContext(AppContext);
  if (!v) throw new Error("useApp outside AppContext");
  return v;
}
