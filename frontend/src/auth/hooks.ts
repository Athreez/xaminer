import { useSyncExternalStore } from "react";

import { api } from "@/api/client";

import { getSession, signedOut, subscribe, type SessionState } from "./session";

export function useSession(): SessionState {
  return useSyncExternalStore(subscribe, getSession);
}

export async function logout(): Promise<void> {
  await api.POST("/api/v1/auth/logout").catch(() => undefined);
  signedOut();
}

export async function logoutEverywhere(): Promise<void> {
  await api.POST("/api/v1/auth/logout-all").catch(() => undefined);
  signedOut();
}
