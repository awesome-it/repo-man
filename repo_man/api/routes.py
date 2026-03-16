"""API v1 routes: publish, health; legacy /api/publish delegates to same service."""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from repo_man.api.deps import get_storage
from repo_man.api.models import HealthResponse, PublishResponse
from repo_man.metrics import publish_duration_seconds, publish_uploads_total
from repo_man.publish_service import publish_packages as publish_service
from repo_man.storage.base import StorageBackend

logger = logging.getLogger(__name__)

router = APIRouter(tags=["v1"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check."""
    return HealthResponse()


async def _parse_uploads_and_publish(
    storage: StorageBackend,
    path_prefix: str,
    format_name: str,
    suite: str,
    component: str,
    arch: str,
    branch: str,
    upload_files: list[UploadFile],
) -> PublishResponse:
    """Parse uploaded files and call shared publish service; returns response model."""
    tmpdir = tempfile.mkdtemp(prefix="repo_man_publish_")
    try:
        tmpdir_path = Path(tmpdir)
        uploads: list[tuple[Path, bytes]] = []
        for uf in upload_files:
            data = await uf.read()
            if not data:
                continue
            fn = uf.filename or "upload"
            safe_name = Path(fn).name
            dest = tmpdir_path / safe_name
            dest.write_bytes(data)
            uploads.append((dest, data))
        if not uploads:
            raise HTTPException(
                status_code=400,
                detail="No non-empty package files; use form field 'packages' or 'files'",
            )
        result = publish_service(
            storage,
            path_prefix,
            format_name,
            suite=suite,
            component=component,
            arch=arch,
            branch=branch,
            uploads=uploads,
        )
        return PublishResponse(
            published=result.published,
            path_prefix=result.path_prefix,
            changed=result.changed,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.post("/publish", response_model=PublishResponse)
async def publish(
    storage: StorageBackend = Depends(get_storage),
    path_prefix: str = Form(..., description="Path prefix for the repo (e.g. /local/)"),
    format: str = Form("apt", description="Format: apt, rpm, or alpine"),
    suite: str = Form("stable", description="Suite (APT)"),
    component: str = Form("main", description="Component (APT)"),
    arch: str = Form("amd64", description="Architecture (APT/RPM)"),
    branch: str = Form("main", description="Branch (Alpine)"),
    packages: list[UploadFile] = File(default=[], description="Package files (alternatively use 'files')"),
    files: list[UploadFile] = File(default=[], description="Package files (alternatively use 'packages')"),
) -> PublishResponse:
    """Publish package files into a repo under the given path prefix."""
    path_prefix = (path_prefix or "").strip()
    if not path_prefix:
        raise HTTPException(status_code=400, detail="path_prefix is required")
    format_name = (format or "apt").strip().lower()
    if format_name not in ("apt", "rpm", "alpine"):
        raise HTTPException(
            status_code=400,
            detail=f"format must be apt, rpm, or alpine; got {format_name!r}",
        )
    upload_files = list(packages) + list(files)
    if not upload_files:
        raise HTTPException(
            status_code=400,
            detail="No package files uploaded; use form field 'packages' or 'files'",
        )
    start = time.perf_counter()
    try:
        result = await _parse_uploads_and_publish(
            storage, path_prefix, format_name,
            suite=suite, component=component, arch=arch, branch=branch,
            upload_files=upload_files,
        )
        publish_uploads_total.labels(path_prefix=path_prefix).inc(result.published)
        publish_duration_seconds.labels(path_prefix=path_prefix).observe(time.perf_counter() - start)
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("API publish failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


# Legacy non-versioned endpoint: same semantics as /api/v1/publish (deprecated).
legacy_router = APIRouter(tags=["legacy"])


@legacy_router.post("/api/publish", response_model=PublishResponse)
async def publish_legacy(
    storage: StorageBackend = Depends(get_storage),
    path_prefix: str = Form(..., description="Path prefix for the repo (e.g. /local/)"),
    format: str = Form("apt", description="Format: apt, rpm, or alpine"),
    suite: str = Form("stable", description="Suite (APT)"),
    component: str = Form("main", description="Component (APT)"),
    arch: str = Form("amd64", description="Architecture (APT/RPM)"),
    branch: str = Form("main", description="Branch (Alpine)"),
    packages: list[UploadFile] = File(default=[], description="Package files"),
    files: list[UploadFile] = File(default=[], description="Package files (alias)"),
) -> PublishResponse:
    """Legacy publish endpoint (deprecated). Use POST /api/v1/publish instead."""
    logger.warning("Legacy POST /api/publish is deprecated; use POST /api/v1/publish")
    path_prefix = (path_prefix or "").strip()
    if not path_prefix:
        raise HTTPException(status_code=400, detail="path_prefix is required")
    format_name = (format or "apt").strip().lower()
    if format_name not in ("apt", "rpm", "alpine"):
        raise HTTPException(
            status_code=400,
            detail=f"format must be apt, rpm, or alpine; got {format_name!r}",
        )
    upload_files = list(packages) + list(files)
    if not upload_files:
        raise HTTPException(
            status_code=400,
            detail="No package files uploaded; use form field 'packages' or 'files'",
        )
    start = time.perf_counter()
    try:
        result = await _parse_uploads_and_publish(
            storage, path_prefix, format_name,
            suite=suite, component=component, arch=arch, branch=branch,
            upload_files=upload_files,
        )
        publish_uploads_total.labels(path_prefix=path_prefix).inc(result.published)
        publish_duration_seconds.labels(path_prefix=path_prefix).observe(time.perf_counter() - start)
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("API publish failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
