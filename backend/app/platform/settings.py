"""Institution settings for admins (PRD PRC-13): evidence retention and default consent text.

Name and timezone are shown but only the platform-admin CLI changes them. The overdue-deletion count
from the architecture doc arrives with the retention job (TCK-1107).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import diff, record
from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.ownership import not_found
from app.authz.permissions import P
from app.platform.consent import standard_consent
from app.platform.models import Institution

ConsentText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]


class InstitutionSettings(BaseModel):
    name: str
    timezone: str
    evidence_retention_days: int = Field(
        description="Evidence images are deleted this many days after the exam closes"
    )
    default_consent_text: str | None = Field(
        description="Shown before proctored exams unless the exam sets its own"
    )
    standard_consent_text: str = Field(
        description="Used when neither the exam nor the institution has its own (video + audio "
        "wording, with this retention)"
    )


class UpdateSettingsRequest(BaseModel):
    """Only the fields sent are changed. Send `default_consent_text: null` to clear it."""

    model_config = ConfigDict(extra="forbid")

    evidence_retention_days: int | None = Field(default=None, ge=7, le=90)
    default_consent_text: ConsentText | None = None


def _view(institution: Institution) -> InstitutionSettings:
    return InstitutionSettings(
        name=institution.name,
        timezone=institution.timezone,
        evidence_retention_days=institution.evidence_retention_days,
        default_consent_text=institution.default_consent_text,
        standard_consent_text=standard_consent("VIDEO_AUDIO", institution.evidence_retention_days),
    )


async def _load(session: AsyncSession, principal: Principal) -> Institution:
    institution = await session.get(Institution, principal.institution_id)
    if institution is None:
        raise not_found()
    return institution


async def update_settings(
    session: AsyncSession, principal: Principal, body: UpdateSettingsRequest
) -> Institution:
    institution = await _load(session, principal)
    sent = body.model_fields_set
    before = {
        "evidence_retention_days": institution.evidence_retention_days,
        "default_consent_text": institution.default_consent_text,
    }
    if "evidence_retention_days" in sent and body.evidence_retention_days is not None:
        institution.evidence_retention_days = body.evidence_retention_days
    if "default_consent_text" in sent:
        institution.default_consent_text = body.default_consent_text
    changes = diff(
        before,
        {
            "evidence_retention_days": institution.evidence_retention_days,
            "default_consent_text": institution.default_consent_text,
        },
    )
    if changes:
        record(
            session,
            "institution.settings_updated",
            institution_id=institution.id,
            actor_id=principal.user_id,
            actor_role=principal.role,
            target_type="institution",
            target_id=institution.id,
            changes=changes,
        )
        await session.commit()
    return institution


router = APIRouter(prefix="/institution/settings", tags=["institution"])

Admin = Annotated[Principal, Depends(require(P.INSTITUTION_SETTINGS_WRITE))]


@router.get("")
async def get_settings(principal: Admin, db: TenantDB) -> InstitutionSettings:
    return _view(await _load(db, principal))


@router.patch("")
async def patch_settings(
    body: UpdateSettingsRequest, principal: Admin, db: TenantDB
) -> InstitutionSettings:
    """Change evidence retention (7 to 90 days) or the default consent text. Audit-logged."""
    return _view(await update_settings(db, principal, body))
