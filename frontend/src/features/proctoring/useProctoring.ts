import { useCallback, useEffect, useRef, useState } from "react";

import type { AttemptView } from "@/features/attempt/lib";
import type { BrowserEvent, ProctorLink } from "@/features/attempt/useExamSession";

import { devicesFor, openCamera, screenLive, shareScreen, stopAll } from "./devices";
import { Proctor } from "./sensing/proctor";

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
  const proctor = useRef<Proctor | null>(null);
  const pending = useRef(new Set<Promise<void>>());
  const recordRef = useRef(record);
  useEffect(() => {
    recordRef.current = record;
  }, [record]);

  const emit = useCallback((event: BrowserEvent) => {
    const p = recordRef.current(event).finally(() => pending.current.delete(p));
    pending.current.add(p);
  }, []);

  // The heartbeat reports frames; before submitting, open events are recorded.
  useEffect(() => {
    if (!active) return;
    link.attach({
      frames: () => proctor.current?.frames ?? 0,
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
          setStream(null);
          setCamera("off");
        });
        setStream(s);
      },
      () => !cancelled && setCamera("off"),
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
          emit,
          onBroken: () => setCamera("broken"),
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
  }, [active, stream, settings, emit]);

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
