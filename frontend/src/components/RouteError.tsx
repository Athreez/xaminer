import { isRouteErrorResponse, Link, useRouteError } from "react-router";

import { Button } from "@/components/ui/button";
import { isStaleChunk } from "@/lib/staleChunk";

/** Shown instead of a page that failed to load or crashed. */
export function RouteError() {
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  const stale = isStaleChunk(error);
  return (
    <main className="bg-background grid min-h-screen place-items-center p-6">
      <div className="bg-card shadow-card max-w-md space-y-3 rounded-xl border p-6 text-center">
        <h1 className="text-xl font-semibold">
          {notFound ? "Page not found" : stale ? "Xaminer was updated" : "Something went wrong"}
        </h1>
        <p className="text-muted-foreground text-sm">
          {notFound
            ? "This page doesn't exist."
            : stale
              ? "Reload to get the new version. Nothing you saved is lost."
              : "This page couldn't be shown. Reloading usually fixes it."}
        </p>
        <div className="flex justify-center gap-2">
          <Button onClick={() => window.location.reload()}>Reload</Button>
          <Button variant="outline" asChild>
            <Link to="/">Home</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
