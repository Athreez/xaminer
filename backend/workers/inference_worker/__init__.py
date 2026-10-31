"""inference-worker: checks proctoring pictures with RT-DETR (phones, books, people) and YuNet
(faces), on the CPU unless a usable GPU is there (TCK-1103).

Run with:  celery -A workers.inference_worker worker -Q inference.verify

It holds no database or storage credentials: a job brings short-lived links to its pictures
(SECURITY_AND_ACCESS.md § 7.2). Models are baked into the image at build time.
"""

from workers.celery_app import celery as app

app.conf.include = ["workers.inference_worker.tasks"]

__all__ = ["app"]
