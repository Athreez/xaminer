"""The two models, loaded once per process.

- RT-DETR r18 (PekingU/rtdetr_r18vd, Apache-2.0), COCO classes: phones, books, people, laptops.
  The threshold is 0.5: CALIPER's measurements found 0.7 missed most phones held low.
- YuNet (OpenCV Zoo, MIT): faces, with their size, for "no face" and "another person".
- SFace (OpenCV Zoo, Apache-2.0): a face's features, compared (cosine) with the student's face
  at the start of the exam. ArcFace would be more accurate, but its weights are research-only.
"""

import io
import os
from dataclasses import dataclass
from functools import cache
from typing import Any

from PIL import Image

from workers.inference_messages import Face, Finding, Thing

RTDETR = os.environ.get("RTDETR_MODEL", "/opt/models/rtdetr_r18vd")
YUNET = os.environ.get("YUNET_MODEL", "/opt/models/face_detection_yunet_2023mar.onnx")
SFACE = os.environ.get("SFACE_MODEL", "/opt/models/face_recognition_sface_2021dec.onnx")
THING_THRESHOLD = 0.5
FACE_THRESHOLD = 0.7
WATCHED = {"cell phone", "book", "person", "laptop"}
MAX_SIDE = 1280


@dataclass
class Models:
    processor: Any
    detector: Any
    device: str


@cache
def models() -> Models:
    import torch

    # The Pillow processor: the default one wants torchvision, which the image doesn't need.
    from transformers import RTDetrForObjectDetection, RTDetrImageProcessorPil

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "1")))  # the worker gets 1.5 cores
    processor = RTDetrImageProcessorPil.from_pretrained(RTDETR)
    detector = RTDetrForObjectDetection.from_pretrained(RTDETR).to(device).eval()
    return Models(processor, detector, device)


def things(image: Image.Image) -> list[Thing]:
    import torch

    m = models()
    inputs = m.processor(images=image, return_tensors="pt").to(m.device)
    with torch.inference_mode():
        outputs = m.detector(**inputs)
    found = m.processor.post_process_object_detection(
        outputs, target_sizes=[(image.height, image.width)], threshold=THING_THRESHOLD
    )[0]
    labels = m.detector.config.id2label
    out = []
    for score, label in zip(found["scores"].tolist(), found["labels"].tolist(), strict=True):
        name = labels[int(label)]
        if name in WATCHED:
            out.append(Thing(label=name, score=round(float(score), 3)))
    return out


def _detect(image: Image.Image) -> tuple[Any, list[Any]]:
    """The picture as OpenCV wants it, and YuNet's face rows, biggest first."""
    import cv2
    import numpy as np

    bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    detector = cv2.FaceDetectorYN.create(YUNET, "", (image.width, image.height), FACE_THRESHOLD)
    _, rows = detector.detect(bgr)
    found = list(rows) if rows is not None else []
    return bgr, sorted(found, key=lambda r: float(r[2] * r[3]), reverse=True)


@cache
def _recognizer() -> Any:
    import cv2

    return cv2.FaceRecognizerSF.create(SFACE, "")


def features(bgr: Any, row: Any) -> Any:
    recognizer = _recognizer()
    return recognizer.feature(recognizer.alignCrop(bgr, row))


def similarity(a: Any, b: Any) -> float:
    import cv2

    return float(_recognizer().match(a, b, cv2.FaceRecognizerSF_FR_COSINE))


def reference(data: bytes) -> Any | None:
    """The main face's features in the reference picture (None when no face is found)."""
    bgr, rows = _detect(open_picture(data))
    return features(bgr, rows[0]) if rows else None


def open_picture(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return image


def look(picture_id: str, data: bytes, known: Any | None = None) -> Finding:
    """What's in one picture; with `known` (the reference's features), how much its main face
    looks like the student at the start."""
    image = open_picture(data)
    bgr, rows = _detect(image)
    total = float(image.width * image.height)
    match = similarity(features(bgr, rows[0]), known) if rows and known is not None else None
    return Finding(
        id=picture_id,
        faces=[
            Face(score=round(float(r[14]), 3), area=round(float(r[2] * r[3]) / total, 4))
            for r in rows
        ],
        things=things(image),
        match=None if match is None else round(match, 3),
    )
