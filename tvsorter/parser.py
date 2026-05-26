from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


QUALITY_RE = re.compile(r"\b(2160p|1080p|720p|480p)\b", re.IGNORECASE)
RELEASE_TRAIL_RE = re.compile(
    r"(?i)\b(2160p|1080p|720p|480p|web[ ._-]?dl|webrip|hdtv|bluray|brrip|x264|x265|h[ ._-]?264|h[ ._-]?265|hevc|aac|ddp?5?[ ._-]?1)\b.*$"
)
YEAR_RE = re.compile(r"(?:^|[\s._(-])((?:19|20)\d{2})(?:$|[\s._)-])")
SXXEYY_RE = re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b")
ONE_X_TWO_RE = re.compile(r"(?i)\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b")
SEASON_EP_RE = re.compile(
    r"(?i)\bseason[\s._-]*(?P<season>\d{1,2})[\s._-]*episode[\s._-]*(?P<episode>\d{1,3})\b"
)


@dataclass(frozen=True)
class ParsedMedia:
    source_name: str
    title: str
    year: int | None
    season: int
    episode: int
    episode_title: str
    quality: str


def parse_media_filename(path: str | Path) -> ParsedMedia:
    source_name = Path(path).name
    stem = Path(path).stem
    season, episode, match = _find_episode(stem)
    quality = detect_quality(stem)
    year = _find_year(stem)
    title = _clean_title(stem[: match.start()] if match else stem)
    episode_title = _clean_episode_title(stem[match.end() :] if match else "")
    return ParsedMedia(
        source_name=source_name,
        title=title or "Unknown Show",
        year=year,
        season=season,
        episode=episode,
        episode_title=episode_title or "Episode",
        quality=quality,
    )


def detect_quality(value: str) -> str:
    match = QUALITY_RE.search(value)
    return match.group(1).lower().replace("p", "p") if match else "Unknown"


def _find_episode(stem: str) -> tuple[int, int, re.Match[str] | None]:
    for pattern in (SXXEYY_RE, ONE_X_TWO_RE, SEASON_EP_RE):
        match = pattern.search(stem)
        if match:
            return int(match.group("season")), int(match.group("episode")), match
    return 1, 1, None


def _find_year(stem: str) -> int | None:
    match = YEAR_RE.search(stem)
    return int(match.group(1)) if match else None


def _clean_title(value: str) -> str:
    value = YEAR_RE.sub(" ", value)
    return _clean_tokens(value)


def _clean_episode_title(value: str) -> str:
    value = RELEASE_TRAIL_RE.sub(" ", value)
    return _clean_tokens(value)


def _clean_tokens(value: str) -> str:
    value = re.sub(r"[\[\](){}]", " ", value)
    value = re.sub(r"[._-]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip().title()
