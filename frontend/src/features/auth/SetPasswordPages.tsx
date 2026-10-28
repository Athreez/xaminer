import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { api, type ApiError } from "@/api/client";
import { tokenFromHash } from "@/auth/helpers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { Field, FormMessage } from "@/components/form";

import { AuthLayout, PasswordInput } from "./AuthLayout";

const MIN_LENGTH = 10; // same as the server (app/auth/passwords.py); the server has the final say
const INVALID_LINK =
  "This link is invalid or has expired. Links work once and expire after a while.";

/**
 * Read the one-time token from `#token=…` once, then remove it from the address bar so it doesn't
 * linger in history or get shared by accident.
 */
function useLinkToken(): string | null {
  const [token] = useState(() => tokenFromHash(window.location.hash));
  useEffect(() => {
    if (window.location.hash) {
      history.replaceState(history.state, "", window.location.pathname + window.location.search);
    }
  }, []);
  return token;
}

function NewPasswordForm({
  onSubmit,
  submitLabel,
}: {
  onSubmit: (password: string) => Promise<string | null>;
  submitLabel: string;
}) {
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<{ field?: "password" | "repeat"; message: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  async function handle(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_LENGTH) {
      return setError({ field: "password", message: `Use at least ${MIN_LENGTH} characters.` });
    }
    if (password !== repeat) {
      return setError({ field: "repeat", message: "The two passwords don't match." });
    }
    setBusy(true);
    setError(null);
    const problem = await onSubmit(password);
    setBusy(false);
    if (problem) setError({ field: "password", message: problem });
  }

  return (
    <form onSubmit={handle} className="space-y-4" noValidate>
      <p className="text-muted-foreground text-sm">
        At least {MIN_LENGTH} characters. Avoid common passwords and your own name or email.
      </p>
      <Field label="New password" error={error?.field === "password" ? error.message : undefined}>
        {(props) => (
          <PasswordInput
            {...props}
            autoComplete="new-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        )}
      </Field>
      <Field label="Repeat password" error={error?.field === "repeat" ? error.message : undefined}>
        {(props) => (
          <PasswordInput
            {...props}
            autoComplete="new-password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
          />
        )}
      </Field>
      <Button type="submit" className="h-11 w-full" disabled={busy}>
        {busy ? "Saving…" : submitLabel}
      </Button>
    </form>
  );
}

/** Turn an API error from set-password into a message for the password field, or throw it up. */
function passwordProblem(error: unknown): string | "INVALID_LINK" {
  const err = (error as ApiError | undefined)?.error;
  if (err?.code === "INVALID_TOKEN") return "INVALID_LINK";
  if (err?.code === "VALIDATION_FAILED") return err.message;
  return "Something went wrong. Try again in a moment.";
}

export function ActivatePage() {
  const token = useLinkToken();
  const navigate = useNavigate();
  const [info, setInfo] = useState<{ full_name: string; institution_name: string } | null>(null);
  const [invalid, setInvalid] = useState(!token);

  useEffect(() => {
    if (!token) return;
    void api.POST("/api/v1/auth/invite/inspect", { body: { token } }).then(({ data }) => {
      if (data) setInfo(data);
      else setInvalid(true);
    });
  }, [token]);

  if (invalid) {
    return (
      <AuthLayout title="Activate your account">
        <FormMessage tone="error">{INVALID_LINK} Ask your admin for a new invitation.</FormMessage>
        <Link to="/login" className="mt-4 block text-sm font-medium text-selection hover:underline">
          Go to log in
        </Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Activate your account"
      subtitle={
        info ? (
          <>
            Welcome, {info.full_name} ({info.institution_name}). Choose a password.
          </>
        ) : (
          "Checking your link…"
        )
      }
    >
      {info && token && (
        <NewPasswordForm
          submitLabel="Activate account"
          onSubmit={async (password) => {
            const { error } = await api.POST("/api/v1/auth/invite/accept", {
              body: { token, password },
            });
            if (!error) {
              navigate("/login", {
                replace: true,
                state: { notice: "Your account is active. Log in with your new password." },
              });
              return null;
            }
            const problem = passwordProblem(error);
            if (problem === "INVALID_LINK") {
              setInvalid(true);
              return null;
            }
            return problem;
          }}
        />
      )}
    </AuthLayout>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handle(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    const { data } = await api.POST("/api/v1/auth/password-reset/request", { body: { email } });
    setBusy(false);
    // The answer is the same whether or not the account exists (SECURITY § 2.1).
    setSent(
      (data as { message?: string } | undefined)?.message ??
        "If an account exists for that email, a reset link has been sent.",
    );
  }

  return (
    <AuthLayout title="Forgot password" subtitle="We'll email you a link to choose a new one.">
      {sent ? (
        <div className="space-y-4">
          <FormMessage tone="success">{sent} The link expires in 1 hour.</FormMessage>
          <Link to="/login" className="block text-sm font-medium text-selection hover:underline">
            Back to log in
          </Link>
        </div>
      ) : (
        <form onSubmit={handle} className="space-y-4" noValidate>
          <Field label="Email">
            {(props) => (
              <Input
                {...props}
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            )}
          </Field>
          <Button type="submit" className="h-11 w-full" disabled={busy || !email}>
            {busy ? "Sending…" : "Send reset link"}
          </Button>
          <Link
            to="/login"
            className="block text-center text-sm font-medium text-selection hover:underline"
          >
            Back to log in
          </Link>
        </form>
      )}
    </AuthLayout>
  );
}

export function ResetPasswordPage() {
  const token = useLinkToken();
  const navigate = useNavigate();
  const [invalid, setInvalid] = useState(!token);

  if (invalid || !token) {
    return (
      <AuthLayout title="Reset password">
        <FormMessage tone="error">{INVALID_LINK}</FormMessage>
        <Link
          to="/forgot-password"
          className="mt-4 block text-sm font-medium text-selection hover:underline"
        >
          Request a new link
        </Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Reset password"
      subtitle="Choose a new password. You'll be logged out everywhere."
    >
      <NewPasswordForm
        submitLabel="Set new password"
        onSubmit={async (password) => {
          const { error } = await api.POST("/api/v1/auth/password-reset/confirm", {
            body: { token, password },
          });
          if (!error) {
            navigate("/login", {
              replace: true,
              state: { notice: "Password changed. Log in with your new password." },
            });
            return null;
          }
          const problem = passwordProblem(error);
          if (problem === "INVALID_LINK") {
            setInvalid(true);
            return null;
          }
          return problem;
        }}
      />
    </AuthLayout>
  );
}
