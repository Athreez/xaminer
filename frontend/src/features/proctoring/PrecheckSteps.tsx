import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Mic, MonitorUp, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
import { MarkdownView } from "@/components/MarkdownView";
import { ErrorState, LoadingRows } from "@/components/page";
import { Button } from "@/components/ui/button";
import { errorText, formatDateTime, unwrap } from "@/lib/api";

import { openCamera, shareScreen, type DeviceSpeed } from "./devices";
import { download, proctoringFiles } from "./downloads";
import { VoiceMonitor } from "./sensing/audio";
import { governedRate, LatencyTracker, median } from "./sensing/geometry";
import { area, VisionEngine } from "./sensing/vision";

/** Share of one CPU core each sensor may use (PRD NFR-07: 30 % for all of proctoring). */
const FACE_BUDGET = 0.2;
const OBJECT_BUDGET = 0.1;
/** Analyses per second wanted (CALIPER's rates), and the least the exam can work with. */
const FACE_TARGET_HZ = 8;
const OBJECT_TARGET_HZ = 2;
export const FACE_MIN_HZ = 1;

type Done<T = void> = (result: T) => void;

/** 1. Consent. The camera isn't touched before this is accepted (SECURITY § 8.1). */
export function ConsentStep({ examId, onDone }: { examId: string; onDone: Done }) {
  const queryClient = useQueryClient();
  const key = ["student", "exams", examId, "consent"];
  const consent = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/student/exams/{exam_id}/consent", {
          params: { path: { exam_id: examId } },
        }),
      ),
  });
  const answer = useMutation({
    mutationFn: async (decision: "ACCEPTED" | "DECLINED") =>
      unwrap(
        await api.POST("/api/v1/student/exams/{exam_id}/consent", {
          params: { path: { exam_id: examId } },
          body: { decision },
        }),
      ),
    onSuccess: (view) => {
      queryClient.setQueryData(key, view);
      if (view.decision === "ACCEPTED") onDone();
    },
  });

  if (consent.isPending) return <LoadingRows rows={4} />;
  if (consent.isError) return <ErrorState error={consent.error} onRetry={consent.refetch} />;
  const view = consent.data;
  return (
    <div className="space-y-4">
      <div className="bg-muted/40 max-h-96 overflow-y-auto rounded-xl border p-4">
        <MarkdownView text={view.text} />
      </div>
      {answer.isError && <FormMessage tone="error">{errorText(answer.error)}</FormMessage>}
      {view.decision === "DECLINED" && (
        <FormMessage tone="info">
          You can't take this exam without agreeing. Contact your teacher. You can still change your
          mind and agree.
        </FormMessage>
      )}
      {view.decision === "ACCEPTED" ? (
        <StepBar text={`You agreed on ${formatDateTime(view.decided_at)}.`}>
          <Button onClick={() => onDone()}>Continue</Button>
        </StepBar>
      ) : (
        <StepBar text="Your camera turns on only after you agree.">
          <Button
            variant="outline"
            disabled={answer.isPending}
            onClick={() => answer.mutate("DECLINED")}
          >
            I don't agree
          </Button>
          <Button disabled={answer.isPending} onClick={() => answer.mutate("ACCEPTED")}>
            I agree
          </Button>
        </StepBar>
      )}
    </div>
  );
}

/** 2. Download the models and runtimes once, so the exam never waits for them. */
export function DownloadStep({ audio, onDone }: { audio: boolean; onDone: Done }) {
  const [progress, setProgress] = useState<{ received: number; total: number | null }>({
    received: 0,
    total: null,
  });
  const [state, setState] = useState<"busy" | "done" | Error>("busy");
  const [attempt, setAttempt] = useState(0);
  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    const abort = new AbortController();
    void (async () => {
      try {
        const files = await proctoringFiles(audio);
        await download(files, (received, total) => setProgress({ received, total }), abort.signal);
        setState("done");
        doneRef.current();
      } catch (e) {
        if (!abort.signal.aborted) setState(e instanceof Error ? e : new Error(String(e)));
      }
    })();
    return () => abort.abort();
  }, [audio, attempt]);

  const mb = (n: number) => `${(n / 1_048_576).toFixed(1)} MB`;
  const percent =
    progress.total && progress.total > 0
      ? Math.min(100, Math.round((progress.received / progress.total) * 100))
      : null;
  if (state instanceof Error) {
    return (
      <div className="space-y-3">
        <FormMessage tone="error">
          The download stopped: {state.message} Check your connection and try again.
        </FormMessage>
        <Button
          onClick={() => {
            setState("busy");
            setAttempt((n) => n + 1);
          }}
        >
          <RefreshCw /> Try again
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm">
        Downloading the checks that run on this computer ({mb(progress.received)}
        {progress.total ? ` of about ${mb(progress.total)}` : ""}). This happens once.
      </p>
      <div
        role="progressbar"
        aria-label="Download"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
        className="bg-muted h-2 overflow-hidden rounded-full"
      >
        <div
          className="bg-primary h-full transition-[width]"
          style={{ width: `${percent ?? (state === "done" ? 100 : 30)}%` }}
        />
      </div>
    </div>
  );
}

/** Why the camera or microphone couldn't be opened, and what to do. */
function deviceProblem(error: unknown, what: string): ReactNode {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError") {
    return (
      <>
        The browser blocked the {what}. Click the camera icon (or the padlock) at the left of the
        address bar, choose <strong>Allow</strong> for the {what}, then press{" "}
        <strong>Check again</strong>. On Windows, also check Settings › Privacy &amp; security ›{" "}
        {what === "screen" ? "Screen capture" : "Camera / Microphone"}.
      </>
    );
  }
  if (name === "NotFoundError") return <>No {what} was found. Connect one and check again.</>;
  if (name === "NotReadableError") {
    return (
      <>The {what} is in use by another app (for example a video call). Close it and check again.</>
    );
  }
  return (
    <>
      The {what} couldn't be opened: {errorText(error)}
    </>
  );
}

/** 3. Camera: a face is in view, and how fast this computer runs the checks. */
export function CameraStep({
  examId,
  microphone,
  onDone,
}: {
  examId: string;
  microphone: boolean;
  onDone: Done<DeviceSpeed>;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [problem, setProblem] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [faces, setFaces] = useState<number | null>(null);
  const [seenMs, setSeenMs] = useState(0);
  const [speed, setSpeed] = useState<DeviceSpeed | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let stopped = false;
    let engine: VisionEngine | null = null;
    let timer = 0;
    const faceMs = new LatencyTracker();
    const objectMs = new LatencyTracker();
    void (async () => {
      try {
        const stream = await openCamera(examId, microphone);
        const el = video.current;
        if (stopped || !el) return;
        el.srcObject = stream;
        await el.play().catch(() => undefined);
        engine = await VisionEngine.create();
        if (stopped) return engine.close();
        setLoading(false);
        let seen = 0;
        let last = performance.now();
        let ticks = 0;
        const tick = () => {
          if (stopped || !engine || !el.videoWidth) {
            timer = window.setTimeout(tick, 200);
            return;
          }
          const now = performance.now();
          const result = engine.faces(el);
          faceMs.add(result.ms);
          // A face counts when it's a reasonable size (not a face far away in the background).
          const main = result.faces.filter((f) => area(f.box) > 0.015);
          seen = main.length === 1 ? seen + (now - last) : 0;
          last = now;
          setFaces(main.length);
          setSeenMs(seen);
          if (ticks++ % 3 === 0) objectMs.add(engine.detect(el).ms);
          const fm = faceMs.ms;
          const om = objectMs.ms;
          if (fm != null) {
            setSpeed({
              faceMs: fm,
              faceDelegate: engine.delegates.face,
              objectMs: om,
              objectDelegate: engine.delegates.objects,
              faceHz: governedRate(FACE_TARGET_HZ, FACE_BUDGET, fm),
              objectHz: om == null ? 0 : governedRate(OBJECT_TARGET_HZ, OBJECT_BUDGET, om),
            });
          }
          timer = window.setTimeout(tick, 150);
        };
        tick();
      } catch (e) {
        if (!stopped) {
          setProblem(e);
          setLoading(false);
        }
      }
    })();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      engine?.close();
    };
  }, [examId, microphone, attempt]);

  const faceSeen = seenMs >= 1500;
  const measured = speed != null && speed.objectMs != null;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-[320px_1fr]">
        <video
          ref={video}
          muted
          playsInline
          aria-label="Your camera"
          className="bg-muted aspect-[4/3] w-full -scale-x-100 rounded-xl border object-cover"
        />
        <div className="space-y-2 text-sm">
          {problem ? (
            <FormMessage tone="error">{deviceProblem(problem, "camera")}</FormMessage>
          ) : loading ? (
            <p>Starting the camera and the face check…</p>
          ) : faces === 0 ? (
            <p>We can't see a face. Sit in front of the camera with your face well lit.</p>
          ) : faces != null && faces > 1 ? (
            <p>We can see more than one face. Only you should be in view.</p>
          ) : faceSeen ? (
            <FormMessage tone="success">We can see your face.</FormMessage>
          ) : (
            <p>Looking for your face… keep still for a moment.</p>
          )}
          {speed && <SpeedText speed={speed} />}
        </div>
      </div>
      <StepBar text="Keep your face in view for the whole exam.">
        {problem != null && (
          <Button
            variant="outline"
            onClick={() => {
              setProblem(null);
              setLoading(true);
              setAttempt((n) => n + 1);
            }}
          >
            <Camera /> Check again
          </Button>
        )}
        <Button disabled={!faceSeen || !measured} onClick={() => speed && onDone(speed)}>
          Continue
        </Button>
      </StepBar>
    </div>
  );
}

function SpeedText({ speed }: { speed: DeviceSpeed }) {
  const slow = speed.faceHz < FACE_MIN_HZ * 2;
  return (
    <div className="text-muted-foreground space-y-1">
      <p>
        Face check: {Math.round(speed.faceMs)} ms ({speed.faceDelegate}), {speed.faceHz.toFixed(1)}{" "}
        times a second.
        {speed.objectMs != null &&
          ` Object check: ${Math.round(speed.objectMs)} ms (${speed.objectDelegate}).`}
      </p>
      {slow && (
        <p>This computer is slow for the checks. The exam still works; close other apps to help.</p>
      )}
    </div>
  );
}

/** 4. Microphone (Video + Audio): speech is heard. The sound never leaves the computer. */
export function MicrophoneStep({ examId, onDone }: { examId: string; onDone: Done }) {
  const [problem, setProblem] = useState<unknown>(null);
  const [level, setLevel] = useState(0);
  const [speechMs, setSpeechMs] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let stopped = false;
    let monitor: VoiceMonitor | null = null;
    let timer = 0;
    void (async () => {
      try {
        const stream = await openCamera(examId, true);
        if (!stream.getAudioTracks().length) throw new DOMException("", "NotFoundError");
        monitor = await VoiceMonitor.start(stream);
        if (stopped) return void monitor.stop();
        timer = window.setInterval(() => {
          setLevel(monitor?.level ?? 0);
          setSpeechMs(monitor?.speechMs ?? 0);
        }, 100);
      } catch (e) {
        if (!stopped) setProblem(e);
      }
    })();
    return () => {
      stopped = true;
      window.clearInterval(timer);
      void monitor?.stop();
    };
  }, [examId, attempt]);

  const heard = speechMs >= 600;
  return (
    <div className="space-y-4">
      {problem ? (
        <FormMessage tone="error">{deviceProblem(problem, "microphone")}</FormMessage>
      ) : (
        <>
          <p className="text-sm">
            Say out loud: <strong>“I am ready for my exam.”</strong>
          </p>
          <div
            role="meter"
            aria-label="Microphone level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(level * 100)}
            className="bg-muted h-3 max-w-sm overflow-hidden rounded-full"
          >
            <div
              className="bg-primary h-full transition-[width] duration-100"
              style={{ width: `${Math.round(level * 100)}%` }}
            />
          </div>
          {heard && <FormMessage tone="success">We can hear you.</FormMessage>}
        </>
      )}
      <StepBar text="Only whether someone is speaking is noted, never what is said.">
        {problem != null && (
          <Button
            variant="outline"
            onClick={() => {
              setProblem(null);
              setAttempt((n) => n + 1);
            }}
          >
            <Mic /> Check again
          </Button>
        )}
        <Button disabled={!heard} onClick={() => onDone()}>
          Continue
        </Button>
      </StepBar>
    </div>
  );
}

/** 5. Share the whole screen (not a window or tab). */
export function ScreenStep({ examId, onDone }: { examId: string; onDone: Done }) {
  const [problem, setProblem] = useState<ReactNode>(null);
  const [shared, setShared] = useState(false);
  const [busy, setBusy] = useState(false);
  const extended = (window.screen as Screen & { isExtended?: boolean }).isExtended === true;

  const share = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const { stream, surface } = await shareScreen(examId);
      if (surface != null && surface !== "monitor") {
        stream.getTracks().forEach((t) => t.stop());
        setProblem(
          <>
            You shared a {surface === "browser" ? "tab" : "window"}. Share your{" "}
            <strong>entire screen</strong> instead.
          </>,
        );
        return;
      }
      stream.getVideoTracks()[0]?.addEventListener("ended", () => setShared(false));
      setShared(true);
    } catch (e) {
      setProblem(deviceProblem(e, "screen"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <ul className="list-disc space-y-1 pl-5 text-sm">
        <li>Close other apps, browser tabs, chats and notes first.</li>
        <li>
          Press <strong>Share my screen</strong>, choose <strong>Entire screen</strong> in the
          browser's window, then <strong>Share</strong>.
        </li>
        <li>
          Pictures of your screen are saved from time to time and when you leave the exam page.
        </li>
      </ul>
      {extended && (
        <FormMessage tone="info">
          More than one screen is connected. Disconnect the others before you start; using them is
          recorded.
        </FormMessage>
      )}
      {problem != null && <FormMessage tone="error">{problem}</FormMessage>}
      {shared && <FormMessage tone="success">Your screen is shared.</FormMessage>}
      <StepBar text="Keep sharing until you submit. Stopping it is recorded.">
        <Button
          variant={shared ? "outline" : "default"}
          disabled={busy}
          onClick={() => void share()}
        >
          <MonitorUp /> {shared ? "Share again" : "Share my screen"}
        </Button>
        <Button disabled={!shared} onClick={() => onDone()}>
          Continue
        </Button>
      </StepBar>
    </div>
  );
}

/** 6. Connection: round trips to the server. Never blocks (answers are kept on the device). */
export function ConnectionStep({ onDone }: { onDone: Done<number | null> }) {
  const [rtt, setRtt] = useState<number | null | "busy">("busy");
  useEffect(() => {
    let stopped = false;
    void (async () => {
      const times: number[] = [];
      for (let i = 0; i < 5 && !stopped; i++) {
        const t0 = performance.now();
        try {
          const r = await fetch("/api/v1/health", { cache: "no-store" });
          if (r.ok) times.push(performance.now() - t0);
        } catch {
          // offline: counted as no answer
        }
      }
      if (!stopped) setRtt(median(times));
    })();
    return () => {
      stopped = true;
    };
  }, []);

  if (rtt === "busy") return <p className="text-sm">Testing your connection…</p>;
  const slow = rtt == null || rtt > 600;
  return (
    <div className="space-y-4">
      {slow ? (
        <FormMessage tone="info">
          {rtt == null
            ? "We couldn't reach the server."
            : `Your connection is slow (${Math.round(rtt)} ms).`}{" "}
          Your answers will still be saved on this computer and sent when it can.
        </FormMessage>
      ) : (
        <FormMessage tone="success">Your connection is fine ({Math.round(rtt)} ms).</FormMessage>
      )}
      <StepBar text="">
        <Button onClick={() => onDone(rtt)}>Continue</Button>
      </StepBar>
    </div>
  );
}

/** 7. Screen size: warns only. */
export function WindowStep({ coding, onDone }: { coding: boolean; onDone: Done }) {
  const [need, needH] = coding ? [1280, 720] : [1024, 768];
  const w = window.screen.width;
  const h = window.screen.height;
  const ok = w >= need && h >= needH;
  return (
    <div className="space-y-4">
      {ok ? (
        <FormMessage tone="success">
          Your screen is {w} × {h}. That's enough.
        </FormMessage>
      ) : (
        <FormMessage tone="info">
          Your screen is {w} × {h}; this exam is easier on at least {need} × {needH}. You can still
          take it.
        </FormMessage>
      )}
      <StepBar text="">
        <Button onClick={() => onDone()}>Continue</Button>
      </StepBar>
    </div>
  );
}

export function StepBar({ text, children }: { text: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
      <p className="text-muted-foreground text-sm">{text}</p>
      <div className="flex gap-2">{children}</div>
    </div>
  );
}
