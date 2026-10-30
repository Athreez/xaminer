import { Camera, CameraOff, ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Proctoring } from "./useProctoring";

/**
 * The exam screen's proctoring corner (FRONTEND_SPEC § 6; TCK-1007): the student's own camera and
 * whether proctoring is on. Neutral wording only: nothing detected is ever shown (PRD PRC-09).
 */
export function ProctoringPanel({ proctoring }: { proctoring: Proctoring }) {
  const { camera, stream } = proctoring;
  const [open, setOpen] = useState(true);
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const el = video.current;
    if (!el || !stream) return;
    el.srcObject = stream;
    void el.play().catch(() => undefined);
    return () => {
      el.srcObject = null;
    };
  }, [stream, open]);

  const on = camera === "on" || camera === "starting";
  return (
    <aside
      aria-label="Proctoring"
      className="bg-card fixed right-3 bottom-3 z-20 w-44 overflow-hidden rounded-md border shadow-md"
    >
      <div className="flex items-center justify-between gap-2 px-2 py-1 text-xs">
        <span className="flex items-center gap-1.5">
          {on ? (
            <Camera aria-hidden className="text-success size-3.5" />
          ) : (
            <CameraOff aria-hidden className="text-warning size-3.5" />
          )}
          {on ? "Proctored" : "Camera off"}
        </span>
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground"
          aria-label={open ? "Hide my camera" : "Show my camera"}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
        </button>
      </div>
      {open && stream && (
        <video
          ref={video}
          muted
          playsInline
          aria-label="Your camera"
          className={cn("aspect-[4/3] w-full -scale-x-100 bg-black object-cover")}
        />
      )}
      {camera === "off" && (
        <div className="space-y-2 p-2 text-xs">
          <p>Your camera was disconnected. Turn it back on to continue being proctored.</p>
          <Button size="sm" className="w-full" onClick={proctoring.reconnectCamera}>
            Turn camera on
          </Button>
        </div>
      )}
      {camera === "broken" && (
        <p className="p-2 text-xs">
          Proctoring stopped working on this computer. Carry on with your exam.
        </p>
      )}
    </aside>
  );
}

/** Shown instead of the questions while the whole screen isn't shared (PRD PRC-17). */
export function ShareScreenAgain({ proctoring }: { proctoring: Proctoring }) {
  const [busy, setBusy] = useState(false);
  return (
    <>
      <h1 className="text-lg font-semibold">Share your screen again</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        This exam needs your whole screen shared until you submit. The questions come back as soon
        as you share it. Time keeps running, and the time without sharing is recorded for your
        teacher.
      </p>
      {proctoring.screenProblem && (
        <p role="alert" className="text-destructive mt-3 text-sm">
          {proctoring.screenProblem}
        </p>
      )}
      <Button
        className="mt-4"
        autoFocus
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await proctoring.shareAgain();
          setBusy(false);
        }}
      >
        Share my screen
      </Button>
    </>
  );
}
