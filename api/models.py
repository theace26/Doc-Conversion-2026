"""
Pydantic request/response models for all MarkFlow API endpoints.

Includes models for: conversion requests/responses, batch status, preview,
history records, preferences, and error responses.
"""

from typing import Any
from pydantic import BaseModel, Field


# ── Conversion ────────────────────────────────────────────────────────────────

class ConvertResponse(BaseModel):
    """Returned immediately after upload; conversion runs asynchronously."""
    batch_id: str = Field(..., examples=["20260307_143000_123456"])
    total_files: int = Field(..., examples=[2])
    message: str = Field(default="Conversion started.")

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "20260307_143000_123456",
                "total_files": 1,
                "message": "Conversion started.",
            }
        }


class PreviewResponse(BaseModel):
    """Analysis result from /api/convert/preview (no actual conversion)."""
    filename: str = Field(..., examples=["report.docx"])
    format: str = Field(..., examples=["docx"])
    file_size_bytes: int = Field(..., examples=[204800])
    page_count: int | None = Field(default=None, examples=[5])
    ocr_likely: bool = Field(default=False)
    warnings: list[str] = Field(default_factory=list)
    element_counts: dict[str, int] = Field(
        default_factory=dict,
        examples=[{"heading": 3, "paragraph": 12, "table": 1}],
    )


# ── Batch status ──────────────────────────────────────────────────────────────

class FileStatus(BaseModel):
    source: str = Field(..., examples=["report.docx"])
    output: str = Field(default="", examples=["report.md"])
    format: str = Field(..., examples=["docx"])
    status: str = Field(..., examples=["success"])
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0)
    ocr_applied: bool = False
    ocr_flags: int = 0
    fidelity_tier: int = Field(default=1, examples=[1, 2, 3])


class BatchStatus(BaseModel):
    batch_id: str
    status: str = Field(..., examples=["done"])  # processing | done | partial | failed
    total_files: int
    completed_files: int = 0
    failed_files: int = 0
    ocr_flags_pending: int = 0
    unattended: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    files: list[FileStatus] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "20260307_143000",
                "status": "done",
                "total_files": 1,
                "completed_files": 1,
                "failed_files": 0,
                "ocr_flags_pending": 0,
                "unattended": False,
                "files": [],
            }
        }


# ── History ───────────────────────────────────────────────────────────────────

class HistoryRecord(BaseModel):
    id: int
    batch_id: str
    source_filename: str
    source_format: str
    output_filename: str
    output_format: str
    direction: str
    source_path: str | None = None
    output_path: str | None = None
    file_size_bytes: int | None = None
    ocr_applied: bool = False
    ocr_flags_total: int = 0
    ocr_flags_resolved: int = 0
    status: str
    error_message: str | None = None
    duration_ms: int | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: str | None = None


class HistoryListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    records: list[HistoryRecord]


class StatsResponse(BaseModel):
    total_conversions: int = 0
    success_count: int = 0
    error_count: int = 0
    success_rate_pct: float = 0.0
    most_used_format: str | None = None
    total_ocr_flags: int = 0
    total_duration_ms: int = 0
    formats: dict[str, int] = Field(default_factory=dict)


# ── Preferences ───────────────────────────────────────────────────────────────

class PreferenceUpdate(BaseModel):
    value: str = Field(..., examples=["80"])

    class Config:
        json_schema_extra = {"example": {"value": "90"}}


# ── Errors ────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
    field: str | None = None
