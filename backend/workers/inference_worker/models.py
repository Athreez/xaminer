"""The two models, loaded once per process.

- RT-DETR r18 (PekingU/rtdetr_r18vd, Apache-2.0), COCO classes: phones, books, people, laptops.
  The threshold is 0.5: CALIPER's measurements found 0.7 missed most phones held low.
- YuNet (OpenCV Zoo, MIT): faces, with their size, for "no face" and "another person".
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
    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
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


def faces(image: Image.Image) -> list[Face]:
    import cv2
    import numpy as np

    bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    detector = cv2.FaceDetectorYN.create(YUNET, "", (image.width, image.height), FACE_THRESHOLD)
    _, rows = detector.detect(bgr)
    total = float(image.width * image.height)
    out = [
        Face(score=round(float(r[14]), 3), area=round(float(r[2] * r[3]) / total, 4))
        for r in (rows if rows is not None else [])
    ]
    return sorted(out, key=lambda f: f.area, reverse=True)


def open_picture(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return image


def look(picture_id: str, data: bytes) -> Finding:
    image = open_picture(data)
    return Finding(id=picture_id, faces=faces(image), things=things(image))
