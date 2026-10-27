import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { homeFor } from "./helpers";
import { useSession } from "./hooks";
import { getSession, refreshSession } from "./session";

/** On page load there is no access token in memory: get one from the refresh cookie. */
export function AuthProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    if (getSession().status === "loading") void refreshSession();
  }, []);
  return children;
}

function FullPageLoading() {
  return (
    <main className="grid min-h-svh place-items-center" aria-busy="true">
      <p className="text-muted-foreground">Loading…</p>
    </main>
  );
}

/**
 * Only lets the given role in. Not logged in → /login, then back here. Wrong role → /403.
 * The server checks every request anyway; this is for a clear experience, not security.
 */
export function RequireRole({ role, children }: { role: string; children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session.status === "loading") return <FullPageLoading />;
  if (session.status === "anonymous") {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  if (session.user.role !== role) return <Navigate to="/403" replace />;
  return children;
}

/** `/`: send each user to their role's home, or to login. */
export function RootRedirect() {
  const session = useSession();
  if (session.status === "loading") return <FullPageLoading />;
  if (session.status === "anonymous") return <Navigate to="/login" replace />;
  return <Navigate to={homeFor(session.user.role)} replace />;
}
