from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness check. Returns OK when the API process is serving requests."""
    return HealthResponse(status="ok")
