import { useCallback, useEffect, useRef, useState } from "react";

import type { AttemptView } from "@/features/attempt/lib";
import type { BrowserEvent, ProctorLink } from "@/features/attempt/useExamSession";

import { devicesFor, openCamera, screenLive, shareScreen, stopAll } from "./devices";
import {
  newPicture,
  PictureQueue,
  screenPicture,
  type PictureKind,
  type Purpose,
} from "./pictures";
import { nextSpotCheck, Proctor } from "./sensing/proctor";

/** Pictures are sent this often (when the student's work is all sent), a few at a time. */
const SEND_EVERY_MS = 2_000;
const SEND_AT_ONCE = 5;
/** A picture of the screen this long after leaving the page (the other window is drawn by then),
 *  at most once per LEFT_EVERY_MS. */
const LEFT_DELAY_MS = 1_500;
const LEFT_EVERY_MS = 10_000;

export type CameraState = "starting" | "on" | "off" | "broken";

export type Proctoring = {
  active: boolean;
  camera: CameraState;
  stream: MediaStream | null;
  /** The whole screen must be shared again: questions stay hidden until then. */
  screenNeeded: boolean;
  screenProblem: string | null;
  reconnectCamera: () => void;
  shareAgain: () => Promise<void>;
};

/**
 * Camera proctoring on the exam screen (PRD PRC-05, PRC-14, PRC-17; TCK-1003..1007). Uses the
 * camera and screen the device check opened (after a reload: the camera is reopened, the screen
 * asked for again). If proctoring breaks the exam carries on; the server notices from the
 * heartbeats. The student never sees what was detected (PRC-09).
 */
export function useProctoring(
  view: AttemptView,
  enabled: boolean,
  record: (event: BrowserEvent) => Promise<void>,
  link: ProctorLink,
): Proctoring {
  const settings = view.proctoring ?? null;
  const active = enabled && settings !== null;
  const examId = view.exam_id;
  const microphone = settings?.mode === "VIDEO_AUDIO";
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [camera, setCamera] = useState<CameraState>("starting");
  const [attempt, setAttempt] = useState(0); // bumped to reconnect the camera
  const [screenNeeded, setScreenNeeded] = useState(
    () => !!settings?.screen_sharing && !screenLive(examId),
  );
  const [screenProblem, setScreenProblem] = useState<string | null>(null);
  const stoppedAt = useRef<number | null>(null);
  const cameraOffAt = useRef<number | null>(null);
  const proctor = useRef<Proctor | null>(null);
  const pending = useRef(new Set<Promise<void>>());
  const recordRef = useRef(record);
  useEffect(() => {
    recordRef.current = record;
  }, [record]);

  // Pictures wait on the device and go behind the student's work, also after submitting while
  // the page is open (PRD PRC-05, PRC-17; TCK-1006).
  const queue = useRef<PictureQueue | null>(null);
  useEffect(() => {
    if (!settings) return;
    let closed = false;
    let busy = false;
    void PictureQueue.open(view.id).then(
      (opened) => (closed ? opened.close() : (queue.current = opened)),
      () => undefined, // no IndexedDB: no pictures, the exam goes on
    );
    const timer = window.setInterval(async () => {
      const q = queue.current;
      const token = link.attemptToken();
      if (busy || !q || !token || !link.idle()) return;
      busy = true;
      try {
        for (let i = 0; i < SEND_AT_ONCE; i++) {
          if ((await q.sendNext(token)) !== "sent") break;
        }
      } catch {
        // tried again next time
      } finally {
        busy = false;
      }
    }, SEND_EVERY_MS);
    return () => {
      closed = true;
      window.clearInterval(timer);
      queue.current?.close();
      queue.current = null;
    };
  }, [settings, view.id, link]);

  const keep = useCallback(
    (kind: PictureKind, purpose: Purpose, blob: Blob, eventId?: string) => {
      void queue.current?.add(newPicture(view.id, kind, purpose, blob, eventId)).catch(() => {});
    },
    [view.id],
  );

  const emit = useCallback((event: BrowserEvent) => {
    const p = recordRef.current(event).finally(() => pending.current.delete(p));
    pending.current.add(p);
  }, []);

  // The heartbeat reports frames; before submitting, open events are recorded.
  useEffect(() => {
    if (!active) return;
    const since = (at: number | null) =>
      at === null ? null : Math.round((Date.now() - at) / 1000);
    link.attach({
      frames: () => proctor.current?.frames ?? 0,
      happening: () => {
        const now = [...(proctor.current?.ongoing() ?? [])];
        const off = since(cameraOffAt.current);
        if (off !== null) now.push({ kind: "CAMERA_OFF", seconds: off });
        const unshared = since(stoppedAt.current);
        if (unshared !== null) now.push({ kind: "SCREEN_SHARE_STOPPED", seconds: unshared });
        return now;
      },
      flush: async () => {
        proctor.current?.flush();
        await Promise.all(pending.current);
      },
    });
    return () => link.attach(null);
  }, [active, link]);

  // The camera: the device check's, or opened again.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const devices = devicesFor(examId);
    const open = devices.camera?.getVideoTracks().some((t) => t.readyState === "live")
      ? Promise.resolve(devices.camera!)
      : openCamera(examId, microphone);
    open.then(
      (s) => {
        if (cancelled) return;
        s.getVideoTracks()[0]?.addEventListener("ended", () => {
          cameraOffAt.current ??= Date.now();
          setStream(null);
          setCamera("off");
        });
        cameraOffAt.current = null;
        setStream(s);
      },
      () => {
        if (cancelled) return;
        cameraOffAt.current ??= Date.now();
        setCamera("off");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [active, examId, microphone, attempt]);

  // Watching, on a video element of its own (the self-view may come and go).
  useEffect(() => {
    if (!active || !stream || !settings) return;
    let cancelled = false;
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    void (async () => {
      try {
        await video.play();
        const started = await Proctor.start({
          video,
          camera: stream,
          config: {
            sensitivity: settings.sensitivity,
            gaze: settings.gaze,
            voice: settings.mode === "VIDEO_AUDIO",
          },
          emit: (e) => emit({ ...e, clientId: e.id }),
          onBroken: () => setCamera("broken"),
          onPicture: (purpose, blob, eventId) => keep("CAMERA", purpose, blob, eventId),
        });
        if (cancelled) return started.stop();
        proctor.current = started;
        setCamera("on");
      } catch {
        if (!cancelled) setCamera("broken");
      }
    })();
    return () => {
      cancelled = true;
      proctor.current?.stop();
      proctor.current = null;
      video.srcObject = null;
    };
  }, [active, stream, settings, emit, keep]);

  // Pictures of the shared screen: every 20-40 s, and on leaving the exam page.
  useEffect(() => {
    if (!active || !settings?.screen_sharing || screenNeeded) return;
    const shared = devicesFor(examId).screen?.stream;
    if (!shared) return;
    const shoot = (purpose: Purpose) =>
      void screenPicture(shared).then((blob) => blob && keep("SCREEN", purpose, blob));
    let periodic = 0;
    const schedule = () => {
      periodic = window.setTimeout(() => {
        shoot("PERIODIC");
        schedule();
      }, nextSpotCheck(0));
    };
    schedule();
    let leftAt = 0;
    let leaving = 0;
    const left = () => {
      const now = Date.now();
      if (now - leftAt < LEFT_EVERY_MS) return;
      leftAt = now;
      leaving = window.setTimeout(() => shoot("LEFT_PAGE"), LEFT_DELAY_MS);
    };
    const onVisibility = () => document.hidden && left();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", left);
    return () => {
      window.clearTimeout(periodic);
      window.clearTimeout(leaving);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", left);
    };
  }, [active, settings, screenNeeded, examId, keep]);

  // The shared screen: stopping it hides the questions until it's shared again.
  useEffect(() => {
    if (!active || !settings?.screen_sharing) return;
    if (screenNeeded) {
      stoppedAt.current ??= Date.now(); // not shared since this page opened (a reload)
      return;
    }
    const track = devicesFor(examId).screen?.stream.getVideoTracks()[0];
    if (!track || track.readyState !== "live") return;
    const ended = () => {
      stoppedAt.current = Date.now();
      setScreenNeeded(true);
    };
    track.addEventListener("ended", ended);
    return () => track.removeEventListener("ended", ended);
  }, [active, settings, examId, screenNeeded]);

  const shareAgain = useCallback(async () => {
    setScreenProblem(null);
    try {
      const { stream: shared, surface } = await shareScreen(examId);
      if (surface != null && surface !== "monitor") {
        shared.getTracks().forEach((t) => t.stop());
        setScreenProblem("Share your entire screen, not a window or a tab.");
        return;
      }
      if (stoppedAt.current !== null) {
        emit({
          kind: "SCREEN_SHARE_STOPPED",
          at: stoppedAt.current,
          durationMs: Date.now() - stoppedAt.current,
        });
        stoppedAt.current = null;
      }
      setScreenNeeded(false);
    } catch {
      setScreenProblem("Screen sharing didn't start. Press the button and choose Entire screen.");
    }
  }, [examId, emit]);

  // Once the exam is over, the camera and screen are turned off.
  const wasActive = useRef(false);
  useEffect(() => {
    if (active) wasActive.current = true;
    else if (wasActive.current) stopAll();
  }, [active]);

  return {
    active,
    camera,
    stream,
    screenNeeded: active && screenNeeded,
    screenProblem,
    reconnectCamera: () => {
      setCamera("starting");
      setAttempt((n) => n + 1);
    },
    shareAgain,
  };
}
