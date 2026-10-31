/**
 * Proctoring pictures (PRD PRC-05, PRC-17; TCK-1006): taken on the device, kept in IndexedDB until
 * sent, and sent only when the student's own work is all saved (architecture § 9.6). They go with
 * the attempt token from the heartbeat, never the access token. On a slow link spot checks are
 * the first to be dropped; event pictures the last.
 */

export type PictureKind = "CAMERA" | "SCREEN";
export type Purpose = "EVENT" | "SPOT_CHECK" | "PERIODIC" | "LEFT_PAGE";

export interface Picture {
  clientId: string;
  attemptId: string;
  kind: PictureKind;
  purpose: Purpose;
  eventClientId?: string;
  takenAt: number;
  blob: Blob;
}

/** Sent first to last; dropped last to first when too many wait. */
const ORDER: Purpose[] = ["EVENT", "LEFT_PAGE", "PERIODIC", "SPOT_CHECK"];
export const MAX_WAITING = 60;

const CAMERA_WIDTH = 640;
const SCREEN_WIDTH = 1280;

/** A JPEG of what's on `source` now, at most `width` wide. */
async function jpeg(
  source: CanvasImageSource,
  w: number,
  h: number,
  width: number,
  quality: number,
): Promise<Blob | null> {
  if (!w || !h) return null;
  const scale = Math.min(1, width / w);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  canvas.getContext("2d")?.drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
}

export function cameraPicture(video: HTMLVideoElement): Promise<Blob | null> {
  return jpeg(video, video.videoWidth, video.videoHeight, CAMERA_WIDTH, 0.7);
}

type FrameGrabber = { grabFrame(): Promise<ImageBitmap> };
type ImageCaptureCtor = new (track: MediaStreamTrack) => FrameGrabber;

/** A picture of the shared screen (Chrome and Edge grab a frame from the track directly, which
 *  works even while the exam's tab is hidden). */
export async function screenPicture(stream: MediaStream): Promise<Blob | null> {
  const track = stream.getVideoTracks()[0];
  if (!track || track.readyState !== "live") return null;
  const Capture = (window as unknown as { ImageCapture?: ImageCaptureCtor }).ImageCapture;
  try {
    if (Capture) {
      const frame = await new Capture(track).grabFrame();
      const blob = await jpeg(frame, frame.width, frame.height, SCREEN_WIDTH, 0.6);
      frame.close();
      return blob;
    }
    const video = document.createElement("video");
    video.muted = true;
    video.srcObject = stream;
    await video.play();
    const blob = await jpeg(video, video.videoWidth, video.videoHeight, SCREEN_WIDTH, 0.6);
    video.srcObject = null;
    return blob;
  } catch {
    return null;
  }
}

export function newPicture(
  attemptId: string,
  kind: PictureKind,
  purpose: Purpose,
  blob: Blob,
  eventClientId?: string,
): Picture {
  return {
    clientId: crypto.randomUUID(),
    attemptId,
    kind,
    purpose,
    takenAt: Date.now(),
    blob,
    ...(eventClientId ? { eventClientId } : {}),
  };
}

const DB_NAME = "xaminer-pictures";
const STORE = "pictures";

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** What a send did: the queue goes on, waits for a new token or for later, or stops for good. */
export type Sent = "sent" | "empty" | "token" | "later" | "closed";

export type Send = (picture: Picture, token: string) => Promise<number>;

/** POST it as a form; the status code, or 0 when the network failed. */
export const sendPicture: Send = async (picture, token) => {
  const form = new FormData();
  form.set("client_id", picture.clientId);
  form.set("kind", picture.kind);
  form.set("purpose", picture.purpose);
  form.set("taken_at", new Date(picture.takenAt).toISOString());
  if (picture.eventClientId) form.set("event_client_id", picture.eventClientId);
  form.set("image", picture.blob, "picture.jpg");
  try {
    const response = await fetch(`/api/v1/attempts/${picture.attemptId}/captures`, {
      method: "POST",
      body: form,
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(20_000),
    });
    return response.status;
  } catch {
    return 0;
  }
};

export class PictureQueue {
  private readonly db: IDBDatabase;
  private readonly attemptId: string;
  private readonly send: Send;

  private constructor(db: IDBDatabase, attemptId: string, send: Send) {
    this.db = db;
    this.attemptId = attemptId;
    this.send = send;
  }

  static async open(
    attemptId: string,
    send: Send = sendPicture,
    factory: IDBFactory = indexedDB,
  ): Promise<PictureQueue> {
    const req = factory.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      req.result
        .createObjectStore(STORE, { keyPath: "clientId" })
        .createIndex("attemptId", "attemptId");
    };
    return new PictureQueue(await request(req), attemptId, send);
  }

  close(): void {
    this.db.close();
  }

  async waiting(): Promise<Picture[]> {
    const store = this.db.transaction(STORE).objectStore(STORE);
    const all = (await request(store.index("attemptId").getAll(this.attemptId))) as Picture[];
    return all.sort(
      (a, b) => ORDER.indexOf(a.purpose) - ORDER.indexOf(b.purpose) || a.takenAt - b.takenAt,
    );
  }

  private async remove(ids: string[]): Promise<void> {
    const store = this.db.transaction(STORE, "readwrite").objectStore(STORE);
    await Promise.all(ids.map((id) => request(store.delete(id))));
  }

  /** Keep a picture; when too many wait, the least useful go first (oldest spot checks...). */
  async add(picture: Picture): Promise<void> {
    await request(this.db.transaction(STORE, "readwrite").objectStore(STORE).put(picture));
    const all = await this.waiting();
    if (all.length <= MAX_WAITING) return;
    const dropOrder = [...all].sort(
      (a, b) => ORDER.indexOf(b.purpose) - ORDER.indexOf(a.purpose) || a.takenAt - b.takenAt,
    );
    await this.remove(dropOrder.slice(0, all.length - MAX_WAITING).map((p) => p.clientId));
  }

  /** Send the next picture. */
  async sendNext(token: string): Promise<Sent> {
    const next = (await this.waiting())[0];
    if (!next) return "empty";
    const status = await this.send(next, token);
    if (status === 401) return "token"; // expired: the next heartbeat brings a new one
    if (status === 409) {
      await this.remove((await this.waiting()).map((p) => p.clientId)); // the attempt is closed
      return "closed";
    }
    if (status === 0 || status === 408 || status === 429 || status >= 500) return "later";
    await this.remove([next.clientId]); // sent, or refused for good (it would never pass)
    return "sent";
  }
}
