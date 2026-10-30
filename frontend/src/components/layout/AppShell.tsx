import { NavLink, Outlet } from "react-router";

import { ThemeToggle } from "@/components/ThemeToggle";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { UserMenu } from "@/components/layout/UserMenu";
import { cn } from "@/lib/utils";

export interface NavItem {
  to: string;
  label: string;
  /** Match only the exact path (for a role's home link). */
  end?: boolean;
}

interface AppShellProps {
  roleLabel: string;
  nav: NavItem[];
  /** Admin and teacher pages use a left sidebar; students get a simple top bar (FRONTEND_SPEC § 4). */
  layout: "sidebar" | "topbar";
}

export function AppShell({ roleLabel, nav, layout }: AppShellProps) {
  const links = nav.map((item) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          "rounded-md px-3 py-2 text-sm font-medium transition-colors",
          "hover:bg-accent hover:text-accent-foreground",
          isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground",
        )
      }
    >
      {item.label}
    </NavLink>
  ));

  const brand = (
    <div className="flex items-baseline gap-2">
      <span className="text-brand-gradient text-xl font-bold">Xaminer</span>
      <span className="text-muted-foreground text-xs uppercase tracking-wide">{roleLabel}</span>
    </div>
  );

  if (layout === "topbar") {
    return (
      <div className="min-h-svh">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:p-2">
          Skip to content
        </a>
        <header className="bg-card/60 border-b backdrop-blur">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
            {brand}
            <nav aria-label="Main" className="flex gap-1">
              {links}
            </nav>
            <div className="ml-auto flex items-center gap-2">
              <NotificationBell />
              <UserMenu compact />
              <ThemeToggle />
            </div>
          </div>
        </header>
        <main id="main" className="mx-auto max-w-5xl px-4 py-6">
          <Outlet />
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-svh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:p-2">
        Skip to content
      </a>
      <aside className="bg-sidebar flex w-60 shrink-0 flex-col border-r px-3 py-4">
        <div className="mb-6 px-3">{brand}</div>
        <nav aria-label="Main" className="flex flex-col gap-1">
          {links}
        </nav>
        <div className="mt-8 space-y-3 border-t pt-4">
          <NotificationBell withLabel />
          <UserMenu />
          <div className="px-1">
            <ThemeToggle />
          </div>
        </div>
      </aside>
      <main id="main" className="flex-1 px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
