/** Small, pure helpers for the auth pages (unit-tested in helpers.test.ts). */

export type Role = "ADMIN" | "TEACHER" | "STUDENT";

const HOME: Record<Role, string> = {
  ADMIN: "/admin/users",
  TEACHER: "/teacher",
  STUDENT: "/student",
};

export function homeFor(role: string): string {
  return HOME[role as Role] ?? "/403";
}

/**
 * Where to go after login, from `?next=`. Only a path on this site is accepted, otherwise a
 * crafted link like `/login?next=https://evil.example` would send users elsewhere after they log
 * in (an "open redirect").
 */
export function safeNextPath(next: string | null): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return null;
  }
  // Control characters (tab, newline...) can confuse URL parsing into leaving the site.
  if ([...next].some((ch) => ch.charCodeAt(0) < 0x20)) return null;
  try {
    const url = new URL(next, "https://xaminer.invalid");
    if (url.origin !== "https://xaminer.invalid") return null;
    if (url.pathname === "/login") return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}

/** The token from an email link: `/activate#token=…` (after `#`, so it never reaches a server). */
export function tokenFromHash(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("token");
  return token && token.length >= 10 ? token : null;
}

/** "Try again after 14:32" in the user's own time. */
export function lockedUntilText(iso: string | undefined): string {
  if (!iso) return "Try again later.";
  const until = new Date(iso);
  if (Number.isNaN(until.getTime())) return "Try again later.";
  const time = until.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `Try again after ${time}.`;
}
