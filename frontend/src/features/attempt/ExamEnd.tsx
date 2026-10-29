import { CheckCircle2, CircleAlert, Clock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, type ApiError } from "@/api/client";
import { loginErrorText } from "@/auth/helpers";
import { signedIn, type User } from "@/auth/session";
import { Field, FormMessage } from "@/components/form";
import { Busy } from "@/components/page";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

import type { Receipt } from "./lib";

/**
 * The receipt (FRONTEND_SPEC § 6.6, § 6.7): proof of submission, what was saved, and honestly
 * what wasn't. Also shown when a finished attempt is opened again (UI state ALREADY_SUBMITTED).
 */
export function ReceiptView({
  receipt,
  title,
  lost = 0,
  hasCoding = false,
  timeUp = false,
  back,
}: {
  receipt: Receipt;
  title?: string;
  lost?: number;
  hasCoding?: boolean;
  timeUp?: boolean;
  back: { to: string; label: string };
}) {
  const auto = receipt.status === "AUTO_SUBMITTED";
  const at = new Date(receipt.submitted_at).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
  return (
    <main className="bg-background grid min-h-svh place-items-center p-6">
      <div className="bg-card shadow-card w-full max-w-lg space-y-5 rounded-2xl border p-6">
        <div className="flex items-start gap-3">
          {auto ? (
            <Clock className="text-warning mt-0.5 size-6 shrink-0" aria-hidden />
          ) : (
            <CheckCircle2 className="text-success mt-0.5 size-6 shrink-0" aria-hidden />
          )}
          <div>
            <h1 className="text-lg font-semibold">
              {auto
                ? `${timeUp ? "Time is up. " : ""}Your exam was submitted automatically.`
                : "Your exam is submitted."}
            </h1>
            {title && <p className="text-muted-foreground text-sm">{title}</p>}
          </div>
        </div>

        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Submitted</dt>
          <dd>
            {at} · {auto ? "automatically" : "by you"}
          </dd>
          <dt className="text-muted-foreground">Answered</dt>
          <dd>
            {receipt.answered} of {receipt.total} questions
          </dd>
          <dt className="text-muted-foreground">Receipt</dt>
          <dd className="font-mono tracking-wide">{receipt.code}</dd>
        </dl>

        {lost > 0 && (
          <p
            className="bg-danger-soft text-destructive flex gap-2 rounded-xl p-3 text-sm"
            role="alert"
          >
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {lost} {lost === 1 ? "change" : "changes"} didn't reach the server before the exam
            ended, so {lost === 1 ? "it isn't" : "they aren't"} part of your submission.
          </p>
        )}
        {hasCoding && (
          <p className="text-muted-foreground text-sm">
            Your last saved code is graded automatically, even if you didn't submit it.
          </p>
        )}
        <p className="text-sm">Results will appear when your teacher releases them.</p>
        <Button asChild>
          <Link to={back.to}>{back.label}</Link>
        </Button>
      </div>
    </main>
  );
}

/**
 * Time is up and the exam is being submitted (§ 6.7). Can't be closed: inputs are locked. The
 * receipt replaces it as soon as the server confirms.
 */
export function TimeUpDialog({ open, unsent }: { open: boolean; unsent: number }) {
  return (
    <Dialog open={open}>
      <DialogContent showCloseButton={false} onEscapeKeyDown={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>Time is up</DialogTitle>
          <DialogDescription>
            {unsent > 0
              ? `Sending your last ${unsent} ${unsent === 1 ? "answer" : "answers"} and submitting. Keep this page open: if the connection is down, we keep trying.`
              : "Submitting your exam…"}
          </DialogDescription>
        </DialogHeader>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The session ran out mid-exam (§ 6.8 rule 2): log in again on top of the exam, never leaving
 * it. Only the same person can continue; answers keep queueing on the device meanwhile.
 */
export function SessionExpiredDialog({ user }: { user: User | null }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!user) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/auth/login", {
        body: { email: user.email, password, institution_id: user.institution_id },
      });
      if (data && data.user.id === user.id) {
        setPassword("");
        signedIn(data);
      } else {
        setError(
          data ? "Log in as yourself." : loginErrorText((apiError as unknown as ApiError).error),
        );
      }
    } catch {
      setError("Can't reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open>
      <DialogContent showCloseButton={false} onEscapeKeyDown={(e) => e.preventDefault()}>
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Log in again to keep going</DialogTitle>
            <DialogDescription>
              Your session ended. Your answers are safe on this device and the timer is still
              running; they're sent as soon as you log in.
            </DialogDescription>
          </DialogHeader>
          {error && <FormMessage tone="error">{error}</FormMessage>}
          <p className="text-sm">
            Logging in as <span className="font-medium">{user.email}</span>
          </p>
          <Field label="Password">
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="current-password"
                autoFocus
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={busy || !password}>
              <Busy busy={busy}>Log in</Busy>
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
