import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Flag, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { api, errorCode } from "@/api/client";
import { useSession } from "@/auth/hooks";
import { MarkdownView } from "@/components/MarkdownView";
import { ErrorState } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AnswerControls } from "@/features/questions/AnswerControls";
import { NO_ANSWER } from "@/features/questions/lib";
import { MarksNote } from "@/features/questions/StudentQuestionCard";
import { unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import { ExamHeader } from "./ExamHeader";
import { canOpen, isAnswered, navState, type AttemptView } from "./lib";
import { QuestionNavigator, type NavItem } from "./QuestionNavigator";
import { ServerClock } from "./sync/clock";
import { useExamSession, type Ended } from "./useExamSession";

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
  if (query.isError) return <Unavailable error={query.error} onRetry={() => query.refetch()} />;
  return <ExamScreen view={query.data.view} clock={query.data.clock} />;
}

function ExamScreen({ view, clock }: { view: AttemptView; clock: ServerClock }) {
  const session = useExamSession(view, clock);
  const me = useSession();
  const preview = me.status === "authenticated" && me.user.role === "TEACHER";
  const sequential = view.navigation_mode === "SEQUENTIAL";
  const items = view.questions;
  const position = usePosition(view.id, items.length);
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
  const navItems: NavItem[] = items.map((q, i) => ({
    number: i + 1,
    state: navState(
      isAnswered(answers[q.exam_question_id]),
      Boolean(flags[q.exam_question_id]),
      visited.has(i),
    ),
    open: canOpen(sequential, i, furthest),
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

  const locked = session.ended !== null;
  const id = item.exam_question_id;
  const answered = isAnswered(answers[id]);
  const last = current === items.length - 1;

  return (
    <div className="bg-background flex min-h-svh flex-col">
      <div className="sticky top-0 z-10">
        <ExamHeader
          title={view.title}
          secondsLeft={session.secondsLeft}
          save={session.save}
          connection={session.connection}
        />
        <Banners session={session} preview={preview ? view.exam_id : null} />
      </div>

      <div className="mx-auto flex w-full max-w-6xl flex-1 gap-6 p-5">
        <aside className="w-60 shrink-0">
          <div className="bg-card rounded-2xl border p-4">
            <QuestionNavigator
              items={navItems}
              current={current}
              sequential={sequential}
              onOpen={(i) => open(i)}
            />
          </div>
        </aside>

        <main className="min-w-0 flex-1">
          <article className="bg-card shadow-card rounded-2xl border p-6" aria-labelledby="q-title">
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
              <Button
                variant="ghost"
                className="mx-auto"
                disabled={locked || !answered || item.question.type === "CODING"}
                onClick={() => session.setAnswer(id, NO_ANSWER)}
              >
                Clear answer
              </Button>
              <div className="flex items-center gap-3">
                {sequential && !last && (
                  <span className="text-muted-foreground text-xs">You can't come back</span>
                )}
                <Button disabled={last} onClick={() => open(current + 1)}>
                  Next <ArrowRight className="size-4" />
                </Button>
              </div>
            </footer>
          </article>
        </main>
      </div>
    </div>
  );
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
}: {
  session: ReturnType<typeof useExamSession>;
  preview: string | null;
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
