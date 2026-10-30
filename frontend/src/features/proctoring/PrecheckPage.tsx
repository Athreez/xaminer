import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
import { ConfirmDialog, ErrorState, LoadingRows, NotFoundBlock } from "@/components/page";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { errorText, isNotFound, unwrap } from "@/lib/api";

import { durationText, type StudentExamDetail } from "../student/lib";
import { devicesFor, screenLive, stopAll, type DeviceSpeed } from "./devices";
import {
  CameraStep,
  ConnectionStep,
  ConsentStep,
  DownloadStep,
  FACE_MIN_HZ,
  MicrophoneStep,
  ScreenStep,
  StepBar,
  WindowStep,
} from "./PrecheckSteps";

type StepKey =
  "consent" | "download" | "camera" | "microphone" | "screen" | "connection" | "window";

const TITLES: Record<StepKey, string> = {
  consent: "Consent",
  download: "Download",
  camera: "Camera",
  microphone: "Microphone",
  screen: "Screen sharing",
  connection: "Connection",
  window: "Screen size",
};

function stepsFor(exam: StudentExamDetail): StepKey[] {
  const steps: StepKey[] = ["consent", "download", "camera"];
  if (exam.proctoring_mode === "VIDEO_AUDIO") steps.push("microphone");
  if (exam.screen_sharing) steps.push("screen");
  steps.push("connection", "window");
  return steps;
}

/**
 * `/student/exams/:examId/precheck`: the device check before a proctored exam (PRD PRC-03,
 * PRC-04; FRONTEND_SPEC § 8.1). Consent first, then the downloads, camera (with a measure of how
 * fast this computer runs the checks), microphone, whole-screen sharing, connection and screen
 * size; then Start. The camera, microphone and screen stay open for the exam.
 */
export function PrecheckPage() {
  const { examId = "" } = useParams();
  // Same key and shape as the instructions page, which this page shares a cache entry with.
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
  const e = exam.data.data;
  if (e.proctoring_mode === "OFF" || e.state !== "AVAILABLE") {
    // Nothing to check (or it's started, done or closed): the instructions page says what's next.
    return <Navigate to={`/student/exams/${examId}`} replace />;
  }
  return <Precheck exam={e} />;
}

function Precheck({ exam }: { exam: StudentExamDetail }) {
  const steps = stepsFor(exam);
  const [index, setIndex] = useState(0);
  const [speed, setSpeed] = useState<DeviceSpeed | null>(null);
  const started = useRef(false);
  const next = () => setIndex((i) => i + 1);

  // Leaving without starting turns the camera, microphone and screen sharing off.
  useEffect(
    () => () => {
      if (!started.current) stopAll();
    },
    [],
  );

  const key = steps[index] as StepKey | undefined;
  return (
    <section className="mx-auto max-w-4xl space-y-4">
      <Link
        to={`/student/exams/${exam.id}`}
        className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft className="size-4" /> Back to the instructions
      </Link>
      <h1 className="text-2xl font-semibold">Device check: {exam.title}</h1>

      <ol className="flex flex-wrap gap-2 text-sm" aria-label="Steps">
        {steps.map((s, i) => (
          <li
            key={s}
            aria-current={i === index ? "step" : undefined}
            className={cn(
              "flex items-center gap-1 rounded-full border px-3 py-1",
              i === index && "border-primary text-primary font-medium",
              i < index && "text-muted-foreground",
            )}
          >
            {i < index ? <Check className="size-3.5" aria-label="done" /> : `${i + 1}.`} {TITLES[s]}
          </li>
        ))}
        <li
          aria-current={index >= steps.length ? "step" : undefined}
          className={cn(
            "rounded-full border px-3 py-1",
            index >= steps.length && "border-primary text-primary font-medium",
          )}
        >
          Ready
        </li>
      </ol>

      <div className="bg-card shadow-card rounded-2xl border p-5">
        <h2 className="mb-4 text-lg font-semibold">{key ? TITLES[key] : "Ready to start"}</h2>
        {key === "consent" && <ConsentStep examId={exam.id} onDone={next} />}
        {key === "download" && (
          <DownloadStep audio={exam.proctoring_mode === "VIDEO_AUDIO"} onDone={next} />
        )}
        {key === "camera" && (
          <CameraStep
            examId={exam.id}
            microphone={exam.proctoring_mode === "VIDEO_AUDIO"}
            onDone={(s) => {
              setSpeed(s);
              devicesFor(exam.id).speed = s;
              next();
            }}
          />
        )}
        {key === "microphone" && <MicrophoneStep examId={exam.id} onDone={next} />}
        {key === "screen" && <ScreenStep examId={exam.id} onDone={next} />}
        {key === "connection" && <ConnectionStep onDone={next} />}
        {key === "window" && <WindowStep coding={exam.has_coding} onDone={next} />}
        {!key && (
          <Ready
            exam={exam}
            speed={speed}
            onStarted={() => {
              started.current = true;
            }}
            onRedo={(step) => setIndex(steps.indexOf(step))}
          />
        )}
      </div>
    </section>
  );
}

function Ready({
  exam,
  speed,
  onStarted,
  onRedo,
}: {
  exam: StudentExamDetail;
  speed: DeviceSpeed | null;
  onStarted: () => void;
  onRedo: (step: StepKey) => void;
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
    onSuccess: (attempt) => {
      onStarted();
      navigate(`/attempt/${attempt.id}`);
    },
    onError: () => setConfirm(false),
  });
  const cameraLive = !!devicesFor(exam.id)
    .camera?.getVideoTracks()
    .some((t) => t.readyState === "live");
  const screenOk = !exam.screen_sharing || screenLive(exam.id);

  return (
    <div className="space-y-4">
      <ul className="space-y-1 text-sm">
        <li>Camera on{exam.proctoring_mode === "VIDEO_AUDIO" ? ", microphone on" : ""}.</li>
        {exam.screen_sharing && <li>Whole screen shared.</li>}
        {speed && (
          <li>
            Checks run {speed.faceHz.toFixed(1)} times a second on this computer
            {speed.faceHz < FACE_MIN_HZ * 2 ? " (slow: close other apps if you can)" : ""}.
          </li>
        )}
      </ul>
      {!cameraLive && (
        <FormMessage tone="error">
          The camera turned off.{" "}
          <Button variant="link" className="h-auto p-0" onClick={() => onRedo("camera")}>
            Check the camera again
          </Button>
        </FormMessage>
      )}
      {!screenOk && (
        <FormMessage tone="error">
          Screen sharing stopped.{" "}
          <Button variant="link" className="h-auto p-0" onClick={() => onRedo("screen")}>
            Share your screen again
          </Button>
        </FormMessage>
      )}
      {start.isError && <FormMessage tone="error">{errorText(start.error)}</FormMessage>}
      <StepBar text={`When you start, you have ${durationText(exam.duration_min)}.`}>
        <Button disabled={!cameraLive || !screenOk} onClick={() => setConfirm(true)}>
          <Play /> Start exam
        </Button>
      </StepBar>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Start the exam now?"
        description={`The timer starts at ${durationText(exam.duration_min)} and keeps running even if you close the page.`}
        confirmLabel="Start"
        busy={start.isPending}
        onConfirm={() => {
          // This click is the user gesture fullscreen needs; the exam screen keeps it.
          if (exam.browser_checks) {
            void document.documentElement.requestFullscreen?.().catch(() => undefined);
          }
          start.mutate();
        }}
      />
    </div>
  );
}
