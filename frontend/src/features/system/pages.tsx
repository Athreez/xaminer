import { Link } from "react-router";

import { Button } from "@/components/ui/button";

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
          <Link to="/">Go to my home page</Link>
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
