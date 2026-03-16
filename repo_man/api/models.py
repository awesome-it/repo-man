"""Pydantic models for the REST API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PublishResponse(BaseModel):
    """Response after publishing packages."""

    published: int = Field(..., description="Number of packages published")
    path_prefix: str = Field(..., description="Path prefix under which packages were published")
    changed: bool = Field(..., description="Whether repository metadata was updated")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="ok", description="Service status")


class ErrorResponse(BaseModel):
    """Error response envelope."""

    error: str = Field(..., description="Error message")
