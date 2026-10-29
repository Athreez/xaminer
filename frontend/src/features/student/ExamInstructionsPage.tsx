import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Play } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
import { MarkdownView } from "@/components/MarkdownView";
import { ConfirmDialog, ErrorState, LoadingRows, NotFoundBlock } from "@/components/page";
import { Button } from "@/components/ui/button";
import { errorText, formatDateTime, isNotFound, unwrap } from "@/lib/api";

import {
  countdown,
  deviceNeeds,
  durationText,
  navigationText,
  proctoringText,
  type StudentExamDetail,
} from "./lib";

/**
 * `/student/exams/:examId`: everything to know before starting (FRONTEND_SPEC § 5.6), then
 * Start (or "Continue to checks" for proctored exams). When the exam isn't open, says why, with a
 * countdown to the opening that follows the server's clock (UI state EXAM_UNAVAILABLE).
 */
export function ExamInstructionsPage() {
  const { examId = "" } = useParams();
  const exam = useQuery({
    queryKey: ["student", "exams", examId],
    queryFn: async () => {
      const data = unwrap(
        await api.GET("/api/v1/student/exams/{exam_id}", {
          params: { path: { exam_id: examId } },
        }),
      );
      return { data, offset: Date.parse(data.server_time) - Date.now() };
    },
  });

  if (exam.isPending) return <LoadingRows rows={6} />;
  if (exam.isError) {
    return isNotFound(exam.error) ? (
      <NotFoundBlock what="exam" back="/student" />
    ) : (
      <ErrorState error={exam.error} onRetry={() => exam.refetch()} />
    );
  }
  return <Instructions exam={exam.data.data} offset={exam.data.offset} onOpened={exam.refetch} />;
}

function Instructions({
  exam,
  offset,
  onOpened,
}: {
  exam: StudentExamDetail;
  offset: number;
  onOpened: () => unknown;
}) {
  const proctored = exam.proctoring_mode !== "OFF";
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link
        to="/student"
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ArrowLeft className="size-4" /> Your exams
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">{exam.title}</h1>
        <p className="text-muted-foreground mt-1">{exam.teacher_name}</p>
      </div>

      <dl className="bg-card shadow-card grid gap-x-6 gap-y-3 rounded-2xl border p-5 text-sm sm:grid-cols-[auto_1fr]">
        <Row label="Window">
          {formatDateTime(exam.open_at)} – {formatDateTime(exam.close_at)}
        </Row>
        <Row label="Time">
          {durationText(exam.duration_min)}, starting when you press Start. It can't be paused.
        </Row>
        <Row label="Questions">
          {exam.question_count}, worth {Number(exam.total_points)} marks in total
        </Row>
        <Row label="Navigation">{navigationText[exam.navigation_mode]}</Row>
        {exam.has_coding && (
          <Row label="Run Code">
            {exam.run_code_enabled
              ? "Available: test your code on the examples before submitting it."
              : "Not available in this exam: submit your code to have it checked."}
          </Row>
        )}
        <Row label="Proctoring">{proctoringText[exam.proctoring_mode]}</Row>
        <Row label="You need">
          <ul className="list-disc space-y-1 pl-4">
            {deviceNeeds(exam).map((need) => (
              <li key={need}>{need}</li>
            ))}
            {exam.has_coding && (
              <li>
                The code editor works with screen readers, though not perfectly. Ask your teacher if
                you need help.
              </li>
            )}
          </ul>
        </Row>
      </dl>

      {exam.instructions.trim() && (
        <section className="bg-card shadow-card rounded-2xl border p-5">
          <h2 className="mb-3 font-semibold">Instructions from your teacher</h2>
          <MarkdownView text={exam.instructions} />
        </section>
      )}

      <StartArea exam={exam} offset={offset} proctored={proctored} onOpened={onOpened} />
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground font-medium">{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

/** Start, Resume, or why not (EXAM_UNAVAILABLE / ALREADY_SUBMITTED). */
function StartArea({
  exam,
  offset,
  proctored,
  onOpened,
}: {
  exam: StudentExamDetail;
  offset: number;
  proctored: boolean;
  onOpened: () => unknown;
}) {
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/student/exams/{exam_id}/attempts", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
    onSuccess: (attempt) => navigate(`/attempt/${attempt.id}`),
    onError: () => setConfirm(false),
  });

  switch (exam.state) {
    case "IN_PROGRESS":
      return (
        <Bar text="You've started this exam. The timer is running.">
          <Button asChild>
            <Link to={`/attempt/${exam.attempt?.id}`}>
              <Play /> Resume exam
            </Link>
          </Button>
        </Bar>
      );
    case "UPCOMING":
      return <OpensIn opensAt={exam.open_at} offset={offset} onOpened={onOpened} />;
    case "TOO_LATE":
      return (
        <FormMessage tone="info">
          Less than 5 minutes are left in the window, so the exam can't be started any more. Talk to
          your teacher.
        </FormMessage>
      );
    case "MISSED":
      return (
        <FormMessage tone="info">
          The exam closed on {formatDateTime(exam.close_at)} before you started it.
        </FormMessage>
      );
    case "SUBMITTED":
      return (
        <Bar text="You've submitted this exam. Results appear when your teacher releases them.">
          {exam.attempt && (
            <Button variant="outline" asChild>
              <Link to={`/attempt/${exam.attempt.id}`}>Receipt</Link>
            </Button>
          )}
        </Bar>
      );
  }

  // AVAILABLE
  if (proctored) {
    return (
      <Bar text="Next: agree to proctoring and check your camera, then start.">
        <Button asChild>
          <Link to={`/student/exams/${exam.id}/precheck`}>
            Continue to checks <ArrowRight />
          </Link>
        </Button>
      </Bar>
    );
  }
  return (
    <>
      {/* e.g. the window closed while this page was open: the server's message says which. */}
      {start.isError && <FormMessage tone="error">{errorText(start.error)}</FormMessage>}
      <Bar text={`When you start, you have ${durationText(exam.duration_min)}.`}>
        <Button onClick={() => setConfirm(true)}>
          <Play /> Start exam
        </Button>
      </Bar>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Start the exam now?"
        description={`The timer starts at ${durationText(exam.duration_min)} and keeps running even if you close the page.`}
        confirmLabel="Start"
        busy={start.isPending}
        onConfirm={() => start.mutate()}
      />
    </>
  );
}

function Bar({ text, children }: { text: string; children?: ReactNode }) {
  return (
    <div className="bg-card shadow-card flex flex-wrap items-center justify-between gap-4 rounded-2xl border p-5">
      <p className="text-sm">{text}</p>
      {children}
    </div>
  );
}

/** A countdown to the opening by the server's clock; at zero the page reloads the exam. */
function OpensIn({
  opensAt,
  offset,
  onOpened,
}: {
  opensAt: string;
  offset: number;
  onOpened: () => unknown;
}) {
  const [now, setNow] = useState(() => Date.now() + offset);
  const left = Date.parse(opensAt) - now;
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() + offset), 1000);
    return () => window.clearInterval(id);
  }, [offset]);
  const opened = left <= 0;
  useEffect(() => {
    if (opened) void onOpened();
  }, [opened, onOpened]);
  return (
    <Bar text={`Not open yet. Opens ${formatDateTime(opensAt)}, ${countdown(left)}.`}>
      <Button disabled>
        <Play /> Start exam
      </Button>
    </Bar>
  );
}
