from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import httpx

from tvsorter.db import Database


@dataclass(frozen=True)
class ShowCandidate:
    provider: str
    provider_id: str
    title: str
    year: int | None
    summary: str


@dataclass(frozen=True)
class EpisodeCandidate:
    provider: str
    provider_show_id: str
    season: int
    episode: int
    title: str


class MetadataProviders:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def search(self, media_type: str, query: str) -> list[ShowCandidate]:
        if media_type == "tv":
            return await self.search_tvmaze(query)
        if media_type == "anime":
            return await self.search_jikan(query)
        if media_type == "film":
            return []
        raise ValueError(f"Unsupported media type: {media_type}")

    async def episodes(self, media_type: str, provider_show_id: str) -> list[EpisodeCandidate]:
        if media_type == "tv":
            return await self.tvmaze_episodes(provider_show_id)
        if media_type == "anime":
            return await self.jikan_episodes(provider_show_id)
        if media_type == "film":
            return []
        raise ValueError(f"Unsupported media type: {media_type}")

    async def search_tvmaze(self, query: str) -> list[ShowCandidate]:
        cache_key = f"tvmaze:search:{query.lower()}"
        cached = self.database.get_cache(cache_key)
        if cached is None:
            url = f"https://api.tvmaze.com/search/shows?q={quote_plus(query)}"
            cached = await _get_json(url)
            self.database.set_cache(cache_key, cached)
        candidates = []
        for item in cached[:10]:
            show = item.get("show", {})
            title = show.get("name") or "Unknown"
            year = _year_from_date(show.get("premiered"))
            summary = _strip_html(show.get("summary") or "")
            candidates.append(
                ShowCandidate(
                    provider="tvmaze",
                    provider_id=str(show.get("id")),
                    title=title,
                    year=year,
                    summary=summary[:240],
                )
            )
        return candidates

    async def tvmaze_episodes(self, provider_show_id: str) -> list[EpisodeCandidate]:
        cache_key = f"tvmaze:episodes:{provider_show_id}"
        cached = self.database.get_cache(cache_key)
        if cached is None:
            url = f"https://api.tvmaze.com/shows/{quote_plus(provider_show_id)}/episodes"
            cached = await _get_json(url)
            self.database.set_cache(cache_key, cached)
        return [
            EpisodeCandidate(
                provider="tvmaze",
                provider_show_id=provider_show_id,
                season=int(item.get("season") or 1),
                episode=int(item.get("number") or 1),
                title=item.get("name") or "Episode",
            )
            for item in cached
            if item.get("number") is not None
        ]

    async def search_jikan(self, query: str) -> list[ShowCandidate]:
        cache_key = f"jikan:search:{query.lower()}"
        cached = self.database.get_cache(cache_key)
        if cached is None:
            url = f"https://api.jikan.moe/v4/anime?q={quote_plus(query)}&limit=10"
            cached = await _get_json(url)
            self.database.set_cache(cache_key, cached)
        candidates = []
        for item in cached.get("data", [])[:10]:
            title = item.get("title_english") or item.get("title") or "Unknown"
            year = item.get("year") or _year_from_date((item.get("aired") or {}).get("from"))
            summary = item.get("synopsis") or ""
            candidates.append(
                ShowCandidate(
                    provider="jikan",
                    provider_id=str(item.get("mal_id")),
                    title=title,
                    year=int(year) if year else None,
                    summary=summary[:240],
                )
            )
        return candidates

    async def jikan_episodes(self, provider_show_id: str) -> list[EpisodeCandidate]:
        cache_key = f"jikan:episodes:{provider_show_id}"
        cached = self.database.get_cache(cache_key)
        if cached is None:
            url = f"https://api.jikan.moe/v4/anime/{quote_plus(provider_show_id)}/episodes"
            cached = await _get_json(url)
            self.database.set_cache(cache_key, cached)
        return [
            EpisodeCandidate(
                provider="jikan",
                provider_show_id=provider_show_id,
                season=1,
                episode=int(item.get("mal_id") or index + 1),
                title=item.get("title") or "Episode",
            )
            for index, item in enumerate(cached.get("data", []))
        ]


async def _get_json(url: str) -> Any:
    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "TvSorter/0.1"}) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _year_from_date(value: str | None) -> int | None:
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def _strip_html(value: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", value).strip()
