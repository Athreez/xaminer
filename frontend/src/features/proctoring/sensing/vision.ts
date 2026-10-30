// MediaPipe Face Landmarker (faces, head pose, blinks, mouth) and Object Detector
// (EfficientDet-Lite0, COCO) on the camera, in the browser (PRD PRC-05). Ported from CALIPER's
// SDK (caliper/frontend/src/sdk/vision.ts): GPU when the browser offers it, else CPU.
import { FaceLandmarker, FilesetResolver, ObjectDetector } from "@mediapipe/tasks-vision";

import { eulerFromMatrix } from "./geometry";

/** Served by the app itself (scripts/proctoring-assets.mjs). */
export const ASSETS = "/proctoring";

export type Box = [number, number, number, number]; // x0, y0, x1, y1, as fractions of the frame

export type Face = {
  box: Box;
  yaw: number | null;
  pitch: number | null;
  blink: number | null; // the more closed eye, 0..1
  jaw: number | null; // mouth open, 0..1
};

export type Detection = { label: string; score: number; box: Box };

export type Delegate = "GPU" | "CPU";

/** Objects the server checks again; everything else is ignored. */
const WATCHED = new Set(["cell phone", "book", "laptop", "person"]);

async function withFallback<T>(
  make: (delegate: Delegate) => Promise<T>,
): Promise<{ task: T; delegate: Delegate }> {
  try {
    return { task: await make("GPU"), delegate: "GPU" };
  } catch {
    return { task: await make("CPU"), delegate: "CPU" };
  }
}

export class VisionEngine {
  private lastFace = 0;
  private lastObjects = 0;

  private readonly face: FaceLandmarker;
  private readonly objects: ObjectDetector | null;
  readonly delegates: { face: Delegate; objects: Delegate | null };

  private constructor(
    face: FaceLandmarker,
    objects: ObjectDetector | null,
    delegates: { face: Delegate; objects: Delegate | null },
  ) {
    this.face = face;
    this.objects = objects;
    this.delegates = delegates;
  }

  static async create({ objects = true } = {}): Promise<VisionEngine> {
    const files = await FilesetResolver.forVisionTasks(`${ASSETS}/mediapipe`);
    const face = await withFallback((delegate) =>
      FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${ASSETS}/models/face_landmarker.task`, delegate },
        runningMode: "VIDEO",
        numFaces: 4,
        outputFaceBlendshapes: true,
        outputFacialTransformationMatrixes: true,
      }),
    );
    const detector = objects
      ? await withFallback((delegate) =>
          ObjectDetector.createFromOptions(files, {
            baseOptions: { modelAssetPath: `${ASSETS}/models/efficientdet_lite0.tflite`, delegate },
            runningMode: "VIDEO",
            scoreThreshold: 0.2, // a hint for the server's check, not a verdict (CALIPER A1 data)
          }),
        )
      : null;
    return new VisionEngine(face.task, detector?.task ?? null, {
      face: face.delegate,
      objects: detector?.delegate ?? null,
    });
  }

  /** VIDEO mode needs strictly increasing timestamps per task. */
  private static stamp(last: number): number {
    const now = performance.now();
    return now > last ? now : last + 1;
  }

  /** Faces in the frame, biggest first, and how long the analysis took. */
  faces(video: HTMLVideoElement): { faces: Face[]; ms: number } {
    const t0 = performance.now();
    this.lastFace = VisionEngine.stamp(this.lastFace);
    const res = this.face.detectForVideo(video, this.lastFace);
    const faces = res.faceLandmarks.map((points, i): Face => {
      let [x0, y0, x1, y1] = [1, 1, 0, 0];
      for (const p of points) {
        x0 = Math.min(x0, p.x);
        y0 = Math.min(y0, p.y);
        x1 = Math.max(x1, p.x);
        y1 = Math.max(y1, p.y);
      }
      const matrix = res.facialTransformationMatrixes?.[i];
      const pose = matrix?.data.length === 16 ? eulerFromMatrix(matrix.data) : null;
      const shapes = res.faceBlendshapes?.[i]?.categories ?? [];
      const shape = (name: string) => shapes.find((c) => c.categoryName === name)?.score ?? null;
      const left = shape("eyeBlinkLeft");
      const right = shape("eyeBlinkRight");
      return {
        box: [x0, y0, x1, y1],
        yaw: pose?.yaw ?? null,
        pitch: pose?.pitch ?? null,
        blink: left == null ? right : right == null ? left : Math.max(left, right),
        jaw: shape("jawOpen"),
      };
    });
    faces.sort((a, b) => area(b.box) - area(a.box));
    return { faces, ms: performance.now() - t0 };
  }

  /** Phones, books, laptops and people in the frame (none when the detector is off). */
  detect(video: HTMLVideoElement): { found: Detection[]; ms: number } {
    if (!this.objects) return { found: [], ms: 0 };
    const t0 = performance.now();
    this.lastObjects = VisionEngine.stamp(this.lastObjects);
    const res = this.objects.detectForVideo(video, this.lastObjects);
    const w = video.videoWidth || 1;
    const h = video.videoHeight || 1;
    const found = res.detections.flatMap((d): Detection[] => {
      const top = d.categories[0];
      const b = d.boundingBox;
      if (!top || !b || !WATCHED.has(top.categoryName)) return [];
      return [
        {
          label: top.categoryName,
          score: top.score,
          box: [
            b.originX / w,
            b.originY / h,
            (b.originX + b.width) / w,
            (b.originY + b.height) / h,
          ],
        },
      ];
    });
    return { found, ms: performance.now() - t0 };
  }

  close(): void {
    this.face.close();
    this.objects?.close();
  }
}

export function area([x0, y0, x1, y1]: Box): number {
  return Math.max(0, x1 - x0) * Math.max(0, y1 - y0);
}
