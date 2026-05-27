from __future__ import annotations

import re
from pathlib import Path


INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_component(value: str) -> str:
    cleaned = INVALID_CHARS.sub(" ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned or "Unknown"


def show_folder_name(title: str, year: int | None) -> str:
    safe_title = sanitize_component(title)
    return f"{safe_title} ({year})" if year else safe_title


def episode_filename(
    title: str,
    year: int | None,
    season: int,
    episode: int,
    episode_title: str,
    quality: str,
    extension: str,
) -> str:
    show = show_folder_name(title, year)
    safe_episode_title = sanitize_component(episode_title)
    safe_quality = sanitize_component(quality)
    return f"{show} - S{season:02d}E{episode:02d} - {safe_episode_title} - {safe_quality}{extension}"


def destination_path(
    output_root: Path,
    title: str,
    year: int | None,
    season: int,
    episode: int,
    episode_title: str,
    quality: str,
    source_path: Path,
) -> Path:
    show = show_folder_name(title, year)
    season_dir = f"Season {season:02d}"
    filename = episode_filename(
        title=title,
        year=year,
        season=season,
        episode=episode,
        episode_title=episode_title,
        quality=quality,
        extension=source_path.suffix,
    )
    return output_root / show / season_dir / filename


def film_destination_path(
    output_root: Path,
    title: str,
    year: int | None,
    quality: str,
    source_path: Path,
) -> Path:
    show = show_folder_name(title, year)
    safe_quality = sanitize_component(quality)
    filename = f"{show} - {safe_quality}{source_path.suffix}"
    return output_root / filename
