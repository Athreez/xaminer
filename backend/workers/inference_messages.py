"""Messages between app-worker and the inference-worker (TECHNICAL_ARCHITECTURE.md § 9.2, § 10).

Like the exec-worker, the inference-worker has no database or storage credentials: a job brings
short-lived links to its pictures. It answers with what the models found, nothing more. Whether
that confirms an event, makes a new one or means nothing is decided in app-worker
(app/proctoring/verdicts.py), never in the worker that looked at student-sent pictures.
"""

from pydantic import BaseModel, Field

JOB_TASK = "inference.job"  # consumed by inference-worker on inference.verify
RESULT_TASK = "inference.result"  # consumed by app-worker on inference.results


class PictureRef(BaseModel):
    id: str
    url: str = Field(description="Pre-signed, a few minutes")


class InferenceJob(BaseModel):
    job_id: str
    pictures: list[PictureRef] = Field(min_length=1, max_length=3)
    reference: PictureRef | None = Field(
        default=None,
        description="The student's face at the start: each picture's main face is compared with it",
    )


class Face(BaseModel):
    score: float
    area: float = Field(description="Share of the picture, 0..1")


class Thing(BaseModel):
    label: str  # COCO: "cell phone", "book", "person", "laptop"
    score: float


class Finding(BaseModel):
    id: str
    faces: list[Face]
    things: list[Thing]
    match: float | None = Field(
        default=None, description="SFace cosine similarity of the main face to the reference"
    )


class InferenceResult(BaseModel):
    job_id: str
    findings: list[Finding] = []
    error: str | None = None  # the pictures couldn't be checked (a link expired, a bad file)
