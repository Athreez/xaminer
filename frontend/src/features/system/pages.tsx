import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";

/** Temporary landing page until login exists (TCK-0110 redirects `/` to the user's home). */
export function HomePage() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/health");
      if (error || !data) throw new Error("API did not answer");
      return data;
    },
  });

  const status = health.isPending
    ? "Checking…"
    : health.isError
      ? "Not reachable"
      : `OK (${health.data.status})`;

  return (
    <main className="mx-auto flex min-h-svh max-w-xl flex-col justify-center gap-6 px-4">
      <h1 className="text-3xl font-semibold">Xaminer</h1>
      <p className="text-muted-foreground">
        Computer-based testing with automated coding evaluation and AI-assisted proctoring.
      </p>
      <p>
        API status: <strong data-testid="api-status">{status}</strong>
      </p>
      <nav aria-label="Areas" className="flex flex-wrap gap-2">
        <Button asChild>
          <Link to="/login">Log in</Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/admin/users">Admin area</Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/teacher">Teacher area</Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/student">Student area</Link>
        </Button>
      </nav>
    </main>
  );
}

/** Stand-in for pages that later tickets build. */
export function PlaceholderPage({ title, ticket }: { title: string; ticket: string }) {
  return (
    <section>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-muted-foreground mt-2">This page is built in {ticket}.</p>
    </section>
  );
}

function ErrorPage({ code, title, message }: { code: string; title: string; message: string }) {
  return (
    <main className="mx-auto flex min-h-svh max-w-md flex-col justify-center gap-4 px-4">
      <p className="text-muted-foreground text-sm font-medium">{code}</p>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-muted-foreground">{message}</p>
      <div>
        <Button asChild>
          <Link to="/">Go to home</Link>
        </Button>
      </div>
    </main>
  );
}

export function ForbiddenPage() {
  return (
    <ErrorPage
      code="403"
      title="You don't have access to this page"
      message="Your account's role can't open this page."
    />
  );
}

/** Same page whether the thing is missing or belongs to someone else (FRONTEND_SPEC § 9). */
export function NotFoundPage() {
  return (
    <ErrorPage
      code="404"
      title="Page not found"
      message="This page doesn't exist, or you don't have access to it."
    />
  );
}
