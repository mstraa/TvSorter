from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".avi",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
}


@dataclass(frozen=True)
class BrowserEntry:
    name: str
    relative_path: str
    absolute_path: Path
    is_dir: bool
    size: int | None
    is_video: bool


def resolve_under_root(root: Path, relative_path: str = "") -> Path:
    root = root.expanduser().resolve()
    target = (root / relative_path).expanduser().resolve()
    if not is_relative_to(target, root):
        raise ValueError("Path is outside the configured root")
    return target


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def list_directory(root: Path, relative_path: str = "") -> list[BrowserEntry]:
    directory = resolve_under_root(root, relative_path)
    if not directory.is_dir():
        raise NotADirectoryError(str(directory))
    entries = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        try:
            stat = child.stat()
        except OSError:
            continue
        relative = child.resolve().relative_to(root.expanduser().resolve())
        entries.append(
            BrowserEntry(
                name=child.name,
                relative_path=str(relative),
                absolute_path=child,
                is_dir=child.is_dir(),
                size=None if child.is_dir() else stat.st_size,
                is_video=is_video_file(child),
            )
        )
    return entries


def expand_video_files(root: Path, relative_paths: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for relative_path in relative_paths:
        target = resolve_under_root(root, relative_path)
        candidates = target.rglob("*") if target.is_dir() else [target]
        for candidate in candidates:
            if candidate.is_file() and is_video_file(candidate):
                resolved = candidate.resolve()
                if resolved not in seen:
                    files.append(resolved)
                    seen.add(resolved)
    return sorted(files)


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS

