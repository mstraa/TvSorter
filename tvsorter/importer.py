from __future__ import annotations

import errno
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from tvsorter.naming import destination_path, film_destination_path


Action = str
ConflictPolicy = str


@dataclass(frozen=True)
class ImportRequest:
    source_path: Path
    output_root: Path
    media_type: str
    show_title: str
    show_year: int | None
    season_number: int
    episode_number: int
    episode_title: str
    quality: str
    action: Action
    conflict_policy: ConflictPolicy
    provider: str | None = None
    provider_show_id: str | None = None


@dataclass(frozen=True)
class ImportResult:
    request: ImportRequest
    output_path: Path
    final_path: Path
    result: str
    error: str | None = None


def preview_import(request: ImportRequest) -> ImportResult:
    output_path = _build_destination(request)
    final_path = _apply_conflict_policy(output_path, request.conflict_policy)
    result = "conflict" if output_path.exists() and final_path == output_path else "preview"
    return ImportResult(request=request, output_path=output_path, final_path=final_path, result=result)


def execute_import(request: ImportRequest) -> ImportResult:
    output_path = _build_destination(request)
    try:
        final_path = _apply_conflict_policy(output_path, request.conflict_policy)
    except FileExistsError as exc:
        return ImportResult(request, output_path, output_path, "failed", str(exc))

    if output_path.exists() and request.conflict_policy == "skip":
        return ImportResult(request, output_path, output_path, "skipped")

    if request.action == "test":
        return ImportResult(request, output_path, final_path, "preview")

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists() and request.conflict_policy == "replace":
            final_path.unlink()
        if request.action == "hardlink":
            os.link(request.source_path, final_path)
        elif request.action == "copy":
            shutil.copy2(request.source_path, final_path)
        else:
            return ImportResult(request, output_path, final_path, "failed", f"Unsupported action: {request.action}")
    except OSError as exc:
        if exc.errno == errno.EXDEV and request.action == "hardlink":
            message = "Hardlink failed because source and destination are on different filesystems."
        else:
            message = _format_os_error(exc, final_path)
        return ImportResult(request, output_path, final_path, "failed", message)

    return ImportResult(request, output_path, final_path, "imported")


def result_to_record(result: ImportResult) -> dict[str, object]:
    source = result.request.source_path
    try:
        stat = source.stat()
        source_size = stat.st_size
        source_mtime = stat.st_mtime
        source_device = stat.st_dev
        source_inode = stat.st_ino
    except OSError:
        source_size = None
        source_mtime = None
        source_device = None
        source_inode = None

    return {
        "source_path": str(source),
        "source_size": source_size,
        "source_mtime": source_mtime,
        "source_device": source_device,
        "source_inode": source_inode,
        "output_path": str(result.final_path),
        "media_type": result.request.media_type,
        "provider": result.request.provider,
        "provider_show_id": result.request.provider_show_id,
        "show_title": result.request.show_title,
        "show_year": result.request.show_year,
        "season_number": result.request.season_number,
        "episode_number": result.request.episode_number,
        "episode_title": result.request.episode_title,
        "quality": result.request.quality,
        "action": result.request.action,
        "conflict_policy": result.request.conflict_policy,
        "result": result.result,
        "error": result.error,
    }


def _build_destination(request: ImportRequest) -> Path:
    if request.media_type == "film":
        return film_destination_path(
            output_root=request.output_root,
            title=request.show_title,
            year=request.show_year,
            quality=request.quality,
            source_path=request.source_path,
        )
    return destination_path(
        output_root=request.output_root,
        title=request.show_title,
        year=request.show_year,
        season=request.season_number,
        episode=request.episode_number,
        episode_title=request.episode_title,
        quality=request.quality,
        source_path=request.source_path,
    )


def _apply_conflict_policy(path: Path, policy: ConflictPolicy) -> Path:
    if not path.exists():
        return path
    if policy == "skip":
        return path
    if policy == "replace":
        return path
    if policy == "fail":
        raise FileExistsError(f"Destination already exists: {path}")
    if policy == "index":
        return _indexed_path(path)
    raise ValueError(f"Unsupported conflict policy: {policy}")


def _indexed_path(path: Path) -> Path:
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"No available indexed destination for: {path}")


def _format_os_error(exc: OSError, destination: Path) -> str:
    if exc.errno in {errno.EACCES, errno.EPERM}:
        return (
            f"Permission denied while writing to {destination.parent}. "
            "Grant the tvsorter service user write access to the output mount, "
            "or adjust the bind-mount ownership/permissions on the Proxmox host."
        )
    return str(exc)
