import { Building2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router";

import { api, type ApiError } from "@/api/client";
import { useSession } from "@/auth/hooks";
import { signedIn } from "@/auth/session";
import { homeFor, lockedUntilText, safeNextPath } from "@/auth/helpers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { Field, FormMessage } from "@/components/form";

import { AuthLayout, PasswordInput } from "./AuthLayout";

interface Choice {
  id: string;
  name: string;
}

/** Messages for each login error (FRONTEND_SPEC § 5.0). */
function messageFor(error: ApiError["error"]): string {
  switch (error.code) {
    case "INVALID_CREDENTIALS":
      return "Email or password is incorrect.";
    case "ACCOUNT_LOCKED":
      return `Too many failed attempts, so this account is locked for a while. ${lockedUntilText(
        error.details?.[0]?.locked_until as string | undefined,
      )}`;
    case "RATE_LIMITED":
      return "Too many attempts from this device. Wait a minute and try again.";
    case "VALIDATION_FAILED":
      return "Enter your email and password.";
    default:
      return "Something went wrong. Try again in a moment.";
  }
}

export function LoginPage() {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const notice = (location.state as { notice?: string } | null)?.notice;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [choices, setChoices] = useState<Choice[] | null>(null);
  const [busy, setBusy] = useState(false);

  if (session.status === "authenticated") {
    return <Navigate to={next ?? homeFor(session.user.role)} replace />;
  }

  async function submit(institutionId?: string) {
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/auth/login", {
        body: { email, password, institution_id: institutionId ?? null },
      });
      if (data) {
        signedIn(data);
        navigate(next ?? homeFor(data.user.role), { replace: true });
        return;
      }
      const err = (apiError as unknown as ApiError).error;
      if (err.code === "INSTITUTION_REQUIRED") {
        setChoices((err.details ?? []) as unknown as Choice[]);
      } else {
        setChoices(null);
        setError(messageFor(err));
      }
    } catch {
      setError("Can't reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  if (choices) {
    return (
      <AuthLayout title="Choose your institution" subtitle="Your account exists in more than one.">
        <div className="space-y-3">
          {choices.map((choice) => (
            <Button
              key={choice.id}
              variant="outline"
              className="h-12 w-full justify-start"
              disabled={busy}
              onClick={() => void submit(choice.id)}
            >
              <Building2 /> {choice.name}
            </Button>
          ))}
          <Button variant="ghost" className="w-full" onClick={() => setChoices(null)}>
            Back
          </Button>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Log in" subtitle="Welcome back to Xaminer.">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {notice && <FormMessage tone="success">{notice}</FormMessage>}
        {error && <FormMessage tone="error">{error}</FormMessage>}
        <Field label="Email">
          {(props) => (
            <Input
              {...props}
              type="email"
              autoComplete="username"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          )}
        </Field>
        <Field label="Password">
          {(props) => (
            <PasswordInput
              {...props}
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        <div className="flex justify-end">
          <Link
            to="/forgot-password"
            className="text-sm font-medium text-selection hover:underline"
          >
            Forgot password?
          </Link>
        </div>
        <Button type="submit" className="h-11 w-full" disabled={busy || !email || !password}>
          {busy ? "Logging in…" : "Log in"}
        </Button>
      </form>
    </AuthLayout>
  );
}
