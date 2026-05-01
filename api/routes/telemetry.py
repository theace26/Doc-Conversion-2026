"""Telemetry endpoint — UI event sink.

Events are logged via structlog to a dedicated subsystem so they can be
filtered easily. Unauthenticated by design (instrumentation should work
on the login page too). Only ui.* events accepted to prevent accidental
log floods if the wrong helper is called.

Spec §13 — preflight checklist: telemetry event taxonomy.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
import structlog

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])
log = structlog.get_logger("ui_telemetry")


class TelemetryEvent(BaseModel):
    event: str = Field(..., min_length=1, max_length=64)
    props: dict = Field(default_factory=dict)


@router.post("", status_code=204)
async def emit(payload: TelemetryEvent, request: Request) -> Response:
    if not payload.event.startswith("ui."):
        raise HTTPException(
            status_code=400,
            detail="telemetry events must start with 'ui.'",
        )
    log.info(
        payload.event,
        ua=request.headers.get("user-agent", "")[:200],
        props=payload.props,
    )
    return Response(status_code=204)
