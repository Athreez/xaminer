/**
 * The camera, microphone and screen the device check opened, kept for the exam screen. The app is
 * a single page, so they stay open from the check to the exam without asking again; a reload
 * loses them (the exam screen then asks to reconnect).
 */

export type ScreenShare = {
  stream: MediaStream;
  /** "monitor" when the whole screen is shared; null when the browser doesn't say. */
  surface: string | null;
};

type Devices = {
  examId: string;
  camera: MediaStream | null;
  screen: ScreenShare | null;
  /** What the device check measured, for the exam screen to pick its rates. */
  speed: DeviceSpeed | null;
};

export type DeviceSpeed = {
  faceMs: number;
  faceDelegate: "GPU" | "CPU";
  objectMs: number | null;
  objectDelegate: "GPU" | "CPU" | null;
  faceHz: number;
  objectHz: number;
};

let current: Devices | null = null;

export function devicesFor(examId: string): Devices {
  if (current?.examId !== examId) {
    stopAll();
    current = { examId, camera: null, screen: null, speed: null };
  }
  return current;
}

function live(stream: MediaStream | null | undefined): boolean {
  return !!stream && stream.getTracks().some((t) => t.readyState === "live");
}

/** The camera (and microphone, when asked for), reusing what's open. */
export async function openCamera(examId: string, microphone: boolean): Promise<MediaStream> {
  const d = devicesFor(examId);
  const hasMic = !!d.camera?.getAudioTracks().some((t) => t.readyState === "live");
  if (live(d.camera) && (!microphone || hasMic)) return d.camera!;
  d.camera?.getTracks().forEach((t) => t.stop());
  d.camera = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 15 } },
    audio: microphone ? { echoCancellation: true, noiseSuppression: false } : false,
  });
  return d.camera;
}

/** Ask the student to share the whole screen (the browser shows its own picker). */
export async function shareScreen(examId: string): Promise<ScreenShare> {
  const d = devicesFor(examId);
  d.screen?.stream.getTracks().forEach((t) => t.stop());
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { displaySurface: "monitor", frameRate: { ideal: 1 } },
    audio: false,
    // Chrome and Edge: offer whole screens, never this tab, and no switching mid-exam.
    ...({
      monitorTypeSurfaces: "include",
      selfBrowserSurface: "exclude",
      surfaceSwitching: "exclude",
    } as object),
  });
  const settings = stream.getVideoTracks()[0]?.getSettings() as
    (MediaTrackSettings & { displaySurface?: string }) | undefined;
  d.screen = { stream, surface: settings?.displaySurface ?? null };
  return d.screen;
}

export function screenLive(examId: string): boolean {
  return current?.examId === examId && live(current.screen?.stream);
}

export function stopAll(): void {
  current?.camera?.getTracks().forEach((t) => t.stop());
  current?.screen?.stream.getTracks().forEach((t) => t.stop());
  current = null;
}
