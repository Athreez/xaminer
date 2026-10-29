"""Image upload for question text (PRD QB-06). Teachers only."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.audit.service import record
from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.core.storage import IMAGES, Storage
from app.images import service

router = APIRouter(prefix="/uploads", tags=["images"])

PREVIEW_SECONDS = 3600  # the editor's preview link; exams sign their own for the exam's length


def storage_of(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


AppStorage = Annotated[Storage, Depends(storage_of)]


class UploadedImage(BaseModel):
    id: uuid.UUID
    ref: str = Field(description="Put this in the Markdown: ![description](ref)")
    url: str = Field(description="A link valid for an hour, for the editor's preview")
    width: int
    height: int
    size_bytes: int


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: Annotated[UploadFile, File(description="PNG, JPEG or WebP, at most 2 MB")],
    principal: Annotated[Principal, Depends(require(P.QUESTION_WRITE))],
    db: TenantDB,
    storage: AppStorage,
) -> UploadedImage:
    """Upload an image for a question. It is checked, cleaned (EXIF removed) and stored as WebP."""
    data = await file.read(service.MAX_BYTES + 1)  # one byte over is enough to know it's too big
    image_id, width, height, size = await service.store(storage, principal.institution_id, data)
    record(
        db,
        "image.uploaded",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="image",
        target_id=image_id,
        changes={"width": width, "height": height, "bytes": size},
    )
    await db.commit()
    return UploadedImage(
        id=image_id,
        ref=f"/api/v1/images/{image_id}",
        url=storage.signed_url(
            IMAGES, service.key_of(principal.institution_id, image_id), PREVIEW_SECONDS
        ),
        width=width,
        height=height,
        size_bytes=size,
    )
