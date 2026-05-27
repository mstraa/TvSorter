from __future__ import annotations

import errno
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


ProgressCallback = Callable[[int, int], None]
CancellationCallback = Callable[[], bool]


class ImportCancelled(Exception):
    pass


def preview_import(request: ImportRequest) -> ImportResult:
    output_path = _build_destination(request)
    final_path = _apply_conflict_policy(output_path, request.conflict_policy)
    result = "conflict" if output_path.exists() and final_path == output_path else "preview"
    return ImportResult(request=request, output_path=output_path, final_path=final_path, result=result)


def execute_import(
    request: ImportRequest,
    progress_callback: ProgressCallback | None = None,
    copy_rate_limit_mbps: float | None = None,
    cancellation_callback: CancellationCallback | None = None,
) -> ImportResult:
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
        if cancellation_callback and cancellation_callback():
            return ImportResult(request, output_path, final_path, "cancelled", "Import cancelled.")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists() and request.conflict_policy == "replace":
            final_path.unlink()
        if request.action == "hardlink":
            if cancellation_callback and cancellation_callback():
                return ImportResult(request, output_path, final_path, "cancelled", "Import cancelled.")
            os.link(request.source_path, final_path)
            if progress_callback:
                progress_callback(1, 1)
        elif request.action == "copy":
            _copy_with_progress(
                request.source_path,
                final_path,
                progress_callback,
                copy_rate_limit_mbps,
                cancellation_callback,
            )
        else:
            return ImportResult(request, output_path, final_path, "failed", f"Unsupported action: {request.action}")
    except ImportCancelled:
        _remove_partial_file(final_path)
        return ImportResult(request, output_path, final_path, "cancelled", "Import cancelled.")
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


def _copy_with_progress(
    source: Path,
    destination: Path,
    progress_callback: ProgressCallback | None = None,
    copy_rate_limit_mbps: float | None = None,
    cancellation_callback: CancellationCallback | None = None,
) -> None:
    total = source.stat().st_size
    copied = 0
    started_at = time.monotonic()
    chunk_size = 256 * 1024
    bytes_per_second = copy_rate_limit_mbps * 1024 * 1024 if copy_rate_limit_mbps and copy_rate_limit_mbps > 0 else None
    with source.open("rb") as source_file, destination.open("wb") as destination_file:
        while True:
            if cancellation_callback and cancellation_callback():
                raise ImportCancelled
            chunk = source_file.read(chunk_size)
            if not chunk:
                break
            destination_file.write(chunk)
            copied += len(chunk)
            if progress_callback:
                progress_callback(copied, total)
            if bytes_per_second:
                expected_elapsed = copied / bytes_per_second
                actual_elapsed = time.monotonic() - started_at
                if expected_elapsed > actual_elapsed:
                    _sleep_until_next_chunk(expected_elapsed - actual_elapsed, cancellation_callback)
    shutil.copystat(source, destination)
    if progress_callback:
        progress_callback(total, total)


def _remove_partial_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _sleep_until_next_chunk(duration: float, cancellation_callback: CancellationCallback | None) -> None:
    deadline = time.monotonic() + duration
    while True:
        if cancellation_callback and cancellation_callback():
            raise ImportCancelled
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.1))


def _format_os_error(exc: OSError, destination: Path) -> str:
    if exc.errno in {errno.EACCES, errno.EPERM}:
        return (
            f"Permission denied while writing to {destination.parent}. "
            "Grant the tvsorter service user write access to the output mount, "
            "or adjust the bind-mount ownership/permissions on the Proxmox host."
        )
    return str(exc)
