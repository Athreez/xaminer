import { useQueries, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, ClipboardCheck, Flag, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { api, errorCode } from "@/api/client";
import { useSession } from "@/auth/hooks";
import type { User } from "@/auth/session";
import { MarkdownView } from "@/components/MarkdownView";
import { ErrorState } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AnswerControls } from "@/features/questions/AnswerControls";
import { NO_ANSWER } from "@/features/questions/lib";
import { MarksNote } from "@/features/questions/StudentQuestionCard";
import { ProctoringPanel, ShareScreenAgain } from "@/features/proctoring/ProctoringPanel";
import { useProctoring } from "@/features/proctoring/useProctoring";
import { unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import { ReceiptView, SessionExpiredDialog, TimeUpDialog } from "./ExamEnd";
import { CodingPanel } from "./coding/CodingPanel";
import { fetchHistory, historyKey } from "./coding/lib";
import { useBrowserChecks } from "./browserChecks";
import { ExamHeader } from "./ExamHeader";
import { canOpen, isAnswered, navState, type AttemptItem, type AttemptView } from "./lib";
import { QuestionNavigator, type NavItem } from "./QuestionNavigator";
import { ReviewPage } from "./ReviewPage";
import { ServerClock } from "./sync/clock";
import { ProctorLink, useExamSession, type Ended } from "./useExamSession";

/**
 * `/attempt/:attemptId`, the exam screen (FRONTEND_SPEC § 6). No app navigation: only the exam.
 * The attempt arrives once with every question; after that the screen works without page loads.
 */
export function ExamScreenPage() {
  const { attemptId = "" } = useParams();
  const query = useQuery({
    queryKey: ["attempt", attemptId],
    queryFn: async () => {
      const sentAt = Date.now();
      const view = unwrap(
        await api.GET("/api/v1/attempts/{attempt_id}", {
          params: { path: { attempt_id: attemptId } },
        }),
      );
      const clock = new ServerClock();
      clock.observe(sentAt, Date.now(), view.server_time);
      return { view, clock };
    },
    // Loaded once: answers then live on the device and in the outbox, never refetched over.
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: (count, error) => count < 3 && !errorCode(error),
  });

  if (query.isPending) return <ScreenSkeleton />;
  if (query.isError) {
    if (errorCode(query.error) === "ALREADY_SUBMITTED") return <AlreadySubmitted id={attemptId} />;
    return <Unavailable error={query.error} onRetry={() => query.refetch()} />;
  }
  return <ExamScreen view={query.data.view} clock={query.data.clock} />;
}

function ExamScreen({ view, clock }: { view: AttemptView; clock: ServerClock }) {
  const [proctorLink] = useState(() => new ProctorLink());
  const session = useExamSession(view, clock, proctorLink);
  const me = useSession();
  // Who is taking the exam, remembered if the session expires (only they may log back in).
  const [user, setUser] = useState<User | null>(null);
  if (me.status === "authenticated" && me.user.id !== user?.id) setUser(me.user);
  const preview = user?.role === "TEACHER";
  // Camera proctoring (when the exam has it; never on a teacher's own preview).
  const proctoring = useProctoring(
    view,
    me.status === "authenticated" && !preview && session.ended === null && !session.receipt,
    session.recordEvent,
    proctorLink,
  );
  // Browser checks (when the exam has them; never on a teacher's own preview).
  const checks = useBrowserChecks(
    view.browser_checks && !preview && session.ended === null && !session.receipt,
    session.recordEvent,
  );
  const [reviewing, setReviewing] = useState(false);
  // Reopened after a reload or on another device: say so (§ 6.2).
  const [restored, setRestored] = useState(
    () => Date.parse(view.server_time) - Date.parse(view.started_at) > 60_000,
  );
  const sequential = view.navigation_mode === "SEQUENTIAL";
  const items = view.questions;
  const position = usePosition(view.id, items.length);
  const wide = useWideScreen();
  const { current, furthest, visited, open } = position;

  // First time on this device (e.g. resumed on another computer): carry on from the last
  // question touched, which for forward-only exams is as far as the student got.
  const { ready, answers, flags } = session;
  const placed = useRef(position.stored);
  useEffect(() => {
    if (!ready || placed.current) return;
    placed.current = true;
    const touched = items.map((q, i) =>
      answers[q.exam_question_id] || flags[q.exam_question_id] ? i : 0,
    );
    open(Math.max(0, ...touched));
  }, [ready, items, answers, flags, open]);

  const item = items[current];
  // Coding questions: "answered" once code is written; a tick once a submission exists (§ 6.4).
  const codingIds = items
    .filter((q) => q.question.type === "CODING")
    .map((q) => q.exam_question_id);
  const histories = useQueries({
    queries: codingIds.map((eq) => ({
      queryKey: historyKey(view.id, eq),
      queryFn: () => fetchHistory(view.id, eq),
      staleTime: 30_000,
    })),
  });
  const submitted = new Set(
    codingIds.filter((_, i) => (histories[i]?.data?.submissions.length ?? 0) > 0),
  );
  const wroteCode = (q: AttemptItem) =>
    Object.entries(session.drafts[q.exam_question_id] ?? {}).some(
      ([key, code]) =>
        code.trim() !== "" &&
        code !== q.question.coding?.languages.find((l) => l.key === key)?.starter_code,
    );
  const navItems: NavItem[] = items.map((q, i) => ({
    number: i + 1,
    state: navState(
      q.question.type === "CODING" ? wroteCode(q) : isAnswered(answers[q.exam_question_id]),
      Boolean(flags[q.exam_question_id]),
      visited.has(i),
    ),
    open: canOpen(sequential, i, furthest),
    submitted: submitted.has(q.exam_question_id),
  }));

  if (session.storageError) {
    return (
      <Centered>
        <h1 className="text-lg font-semibold">This browser can't keep your answers safe</h1>
        <p className="text-muted-foreground mt-2 text-sm">
          The exam saves every answer on this device first, and this browser refused (private
          windows sometimes do). Open the exam in a normal window of Chrome, Edge or Firefox.
        </p>
      </Centered>
    );
  }
  if (!session.ready || !item) return <ScreenSkeleton />;
  if (session.receipt) {
    return (
      <ReceiptView
        receipt={session.receipt}
        title={view.title}
        lost={session.lost}
        hasCoding={items.some((q) => q.question.type === "CODING")}
        timeUp={session.secondsLeft === 0}
        back={backLink(preview, view.exam_id)}
      />
    );
  }

  const panel = proctoring.active && <ProctoringPanel proctoring={proctoring} />;
  if (!checks.inFullscreen) {
    return (
      <Centered>
        <h1 className="text-lg font-semibold">This exam runs in fullscreen</h1>
        <p className="text-muted-foreground mt-2 text-sm">
          The questions come back as soon as you return to fullscreen. Time keeps running, and
          leaving fullscreen is recorded for your teacher.
        </p>
        <Button className="mt-4" onClick={checks.enterFullscreen} autoFocus>
          Return to fullscreen
        </Button>
        {panel}
      </Centered>
    );
  }

  if (proctoring.screenNeeded) {
    return (
      <Centered>
        <ShareScreenAgain proctoring={proctoring} />
        {panel}
      </Centered>
    );
  }

  const locked = session.ended !== null;
  const coding = item.question.type === "CODING";
  const id = item.exam_question_id;
  const answered = isAnswered(answers[id]);
  const last = current === items.length - 1;

  return (
    <div className="bg-background flex min-h-svh flex-col">
      {panel}
      <div className="sticky top-0 z-10">
        <ExamHeader
          title={view.title}
          secondsLeft={session.secondsLeft}
          save={session.save}
          connection={session.connection}
        />
        {checks.notice && (
          <div
            role="status"
            className="bg-warning-soft text-warning flex items-center justify-between gap-3 border-b px-4 py-2 text-sm"
          >
            <span>{checks.notice}</span>
            <Button size="sm" variant="ghost" onClick={checks.dismissNotice}>
              OK
            </Button>
          </div>
        )}
        <Banners
          session={session}
          preview={preview ? view.exam_id : null}
          restored={restored}
          onRestoredSeen={() => setRestored(false)}
        />
      </div>

      <TimeUpDialog open={session.ended === "TIME_UP"} unsent={session.save.unsent} />
      {me.status === "anonymous" && <SessionExpiredDialog user={user} />}

      {reviewing ? (
        <ReviewPage
          rows={items.map((q, i) => ({
            item: q,
            state: navItems[i]!.state,
            open: navItems[i]!.open,
            submitted: submitted.has(q.exam_question_id),
          }))}
          session={session}
          onBack={() => setReviewing(false)}
          onOpen={(i) => {
            open(i);
            setReviewing(false);
          }}
        />
      ) : (
        <div
          className={cn(
            "mx-auto flex w-full flex-1 gap-6 p-5",
            coding ? "max-w-[1680px]" : "max-w-6xl",
          )}
        >
          <aside className="w-60 shrink-0">
            <div className="bg-card rounded-2xl border p-4">
              <QuestionNavigator
                items={navItems}
                current={current}
                sequential={sequential}
                onOpen={(i) => open(i)}
              />
              <Button variant="outline" className="mt-4 w-full" onClick={() => setReviewing(true)}>
                <ClipboardCheck className="size-4" /> Review &amp; submit
              </Button>
            </div>
          </aside>

          <main className="min-w-0 flex-1">
            <article
              className="bg-card shadow-card rounded-2xl border p-6"
              aria-labelledby="q-title"
            >
              <header className="mb-4 flex flex-wrap items-center gap-3">
                <h2 id="q-title" className="mr-auto text-sm font-semibold">
                  Question {current + 1} of {items.length}
                </h2>
                <Button
                  variant={flags[id] ? "secondary" : "outline"}
                  size="sm"
                  aria-pressed={Boolean(flags[id])}
                  disabled={locked}
                  onClick={() => session.setFlag(id, !flags[id])}
                >
                  <Flag className={cn("size-4", flags[id] && "fill-warning text-warning")} />
                  {flags[id] ? "Marked for review" : "Mark for review"}
                </Button>
                <span className="text-muted-foreground flex gap-3 text-sm">
                  <MarksNote question={item.question} />
                </span>
              </header>

              {coding ? (
                <CodingPanel
                  key={id}
                  attemptId={view.id}
                  item={item}
                  session={session}
                  runCodeEnabled={view.run_code_enabled}
                  countedRule={view.counted_submission}
                  wide={wide}
                />
              ) : (
                <>
                  <MarkdownView text={item.question.body} />
                  <div className="mt-6">
                    <AnswerControls
                      key={id}
                      question={item.question}
                      value={answers[id] ?? NO_ANSWER}
                      disabled={locked}
                      onChange={(value) =>
                        session.setAnswer(id, value, item.question.type === "DESCRIPTIVE")
                      }
                    />
                  </div>
                </>
              )}

              <footer className="mt-8 flex flex-wrap items-center gap-3 border-t pt-5">
                {!sequential && (
                  <Button
                    variant="outline"
                    disabled={current === 0}
                    onClick={() => open(current - 1)}
                  >
                    <ArrowLeft className="size-4" /> Previous
                  </Button>
                )}
                {coding ? (
                  <span className="mx-auto" />
                ) : (
                  <Button
                    variant="ghost"
                    className="mx-auto"
                    disabled={locked || !answered}
                    onClick={() => session.setAnswer(id, NO_ANSWER)}
                  >
                    Clear answer
                  </Button>
                )}
                <div className="flex items-center gap-3">
                  {sequential && !last && (
                    <span className="text-muted-foreground text-xs">You can't come back</span>
                  )}
                  {last ? (
                    <Button onClick={() => setReviewing(true)}>
                      Review &amp; submit <ArrowRight className="size-4" />
                    </Button>
                  ) : (
                    <Button onClick={() => open(current + 1)}>
                      Next <ArrowRight className="size-4" />
                    </Button>
                  )}
                </div>
              </footer>
            </article>
          </main>
        </div>
      )}
    </div>
  );
}

function backLink(preview: boolean, examId: string) {
  return preview
    ? { to: `/teacher/exams/${examId}`, label: "Back to the exam" }
    : { to: "/student", label: "Back to your exams" };
}

/** Opening an attempt that is already over shows its receipt (UI state ALREADY_SUBMITTED). */
function AlreadySubmitted({ id }: { id: string }) {
  const me = useSession();
  const receipt = useQuery({
    queryKey: ["attempt", id, "receipt"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/attempts/{attempt_id}/receipt", {
          params: { path: { attempt_id: id } },
        }),
      ),
  });
  if (receipt.isPending) return <ScreenSkeleton />;
  if (receipt.isError)
    return <Unavailable error={receipt.error} onRetry={() => receipt.refetch()} />;
  const preview = me.status === "authenticated" && me.user.role === "TEACHER";
  return <ReceiptView receipt={receipt.data} back={backLink(preview, receipt.data.exam_id)} />;
}

// ----------------------------------------------------------------------------- position

interface Position {
  current: number;
  furthest: number;
  visited: number[];
}

/**
 * Which question is open, the furthest reached (sequential exams can't go back before it) and
 * which were seen. Kept on this device, so a reload opens the same question.
 */
function usePosition(attemptId: string, count: number) {
  const key = `xaminer-position:${attemptId}`;
  const [saved] = useState(() => readPosition(key));
  const [position, setPosition] = useState<Position>(
    () => saved ?? { current: 0, furthest: 0, visited: [0] },
  );

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(position));
    } catch {
      // Storage unavailable: the position just isn't remembered across reloads.
    }
  }, [key, position]);

  // Callers only offer questions that may be opened (`canOpen`).
  const open = useCallback(
    (index: number) => {
      setPosition((p) => {
        const to = Math.max(0, Math.min(count - 1, index));
        return {
          current: to,
          furthest: Math.max(p.furthest, to),
          visited: p.visited.includes(to) ? p.visited : [...p.visited, to],
        };
      });
    },
    [count],
  );

  return {
    current: Math.min(position.current, Math.max(0, count - 1)),
    furthest: position.furthest,
    visited: new Set(position.visited),
    stored: saved !== null,
    open,
  };
}

function readPosition(key: string): Position | null {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "null") as Position | null;
    return value && Number.isInteger(value.current) && Array.isArray(value.visited) ? value : null;
  } catch {
    return null;
  }
}

// ----------------------------------------------------------------------------- banners

function Banners({
  session,
  preview,
  restored,
  onRestoredSeen,
}: {
  session: ReturnType<typeof useExamSession>;
  preview: string | null;
  restored: boolean;
  onRestoredSeen: () => void;
}) {
  const small = useWindowTooSmall();
  const { secondsLeft, ended, extendedBy } = session;
  return (
    <div className="space-y-px">
      {preview && (
        <Banner tone="info">
          Preview: you're taking your exam as a student would. It never counts.{" "}
          <Link className="font-medium underline" to={`/teacher/exams/${preview}`}>
            Leave preview
          </Link>
        </Banner>
      )}
      {restored && !ended && (
        <Banner tone="info" onClose={onRestoredSeen}>
          Your answers were restored. The timer kept running.
        </Banner>
      )}
      {ended && <Banner tone="danger">{endedText(ended, session.save.unsent)}</Banner>}
      {!ended && secondsLeft > 0 && secondsLeft <= 120 && (
        <Banner tone="danger">
          Less than 2 minutes left. Your answers are saved as you go; the exam submits itself at
          zero.
        </Banner>
      )}
      {extendedBy !== null && (
        <Banner tone="info" onClose={session.dismissExtension}>
          Your teacher added {extendedBy} {extendedBy === 1 ? "minute" : "minutes"}.
        </Banner>
      )}
      {small && (
        <Banner tone="warning">
          This window is small. Make it larger (at least 1024 × 768) to see the whole exam.
        </Banner>
      )}
    </div>
  );
}

function endedText(ended: Ended, unsent: number): string {
  switch (ended) {
    case "TIME_UP":
      return unsent > 0
        ? `Time is up. Sending your last ${unsent} ${unsent === 1 ? "change" : "changes"}…`
        : "Time is up. Your answers are saved and can't be changed any more.";
    case "SUBMITTED":
    case "AUTO_SUBMITTED":
      return "This exam has been submitted. Answers can't be changed any more.";
    case "VOIDED":
      return "Your teacher reset this attempt. Answers here are no longer saved.";
  }
}

const toneClass = {
  info: "bg-selection-soft text-foreground",
  warning: "bg-warning-soft text-foreground",
  danger: "bg-danger-soft text-destructive font-medium",
};

function Banner({
  tone,
  children,
  onClose,
}: {
  tone: keyof typeof toneClass;
  children: ReactNode;
  onClose?: () => void;
}) {
  return (
    <div role="status" className={cn("flex items-center gap-3 px-5 py-2 text-sm", toneClass[tone])}>
      <p className="flex-1">{children}</p>
      {onClose && (
        <button type="button" aria-label="Dismiss" onClick={onClose} className="rounded p-1">
          <X className="size-4" />
        </button>
      )}
    </div>
  );
}

/** At least 1280 px wide: the coding panel shows problem, code and results side by side. */
function useWideScreen(): boolean {
  const check = () => window.innerWidth >= 1280;
  const [wide, setWide] = useState(check);
  useEffect(() => {
    const update = () => setWide(check());
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return wide;
}

function useWindowTooSmall(): boolean {
  const check = () => window.innerWidth < 1024 || window.innerHeight < 640;
  const [small, setSmall] = useState(check);
  useEffect(() => {
    const update = () => setSmall(check());
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return small;
}

// ----------------------------------------------------------------------------- loading / errors

function ScreenSkeleton() {
  return (
    <div className="flex min-h-svh flex-col" aria-busy>
      <div className="border-b px-5 py-3">
        <Skeleton className="h-6 w-64" />
      </div>
      <div className="mx-auto flex w-full max-w-6xl gap-6 p-5">
        <Skeleton className="h-80 w-60 rounded-2xl" />
        <Skeleton className="h-96 flex-1 rounded-2xl" />
      </div>
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="bg-background grid min-h-svh place-items-center p-6">
      <div className="bg-card max-w-md rounded-2xl border p-6">{children}</div>
    </div>
  );
}

function Unavailable({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const code = errorCode(error);
  if (code === "ALREADY_SUBMITTED" || code === "NOT_FOUND") {
    return (
      <Centered>
        <h1 className="text-lg font-semibold">
          {code === "ALREADY_SUBMITTED" ? "You've already submitted this exam" : "Exam not found"}
        </h1>
        <p className="text-muted-foreground mt-2 text-sm">
          {code === "ALREADY_SUBMITTED"
            ? "Results will appear when your teacher releases them."
            : "This attempt doesn't exist or isn't yours."}
        </p>
        <Button asChild className="mt-4">
          <Link to="/">Back to your exams</Link>
        </Button>
      </Centered>
    );
  }
  return (
    <Centered>
      <ErrorState error={error} onRetry={onRetry} />
    </Centered>
  );
}
