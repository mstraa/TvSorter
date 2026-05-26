from __future__ import annotations

import asyncio
import time
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
        self._last_jikan_request = 0.0

    async def search(self, media_type: str, query: str) -> list[ShowCandidate]:
        if media_type == "tv":
            return await self.search_tvmaze(query)
        if media_type == "anime":
            return await self.search_jikan(query)
        if media_type == "film":
            return await self.search_wikidata_films(query)
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
            await self._throttle_jikan()
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
            await self._throttle_jikan()
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

    async def search_wikidata_films(self, query: str) -> list[ShowCandidate]:
        cache_key = f"wikidata:film:search:{query.lower()}"
        cached = self.database.get_cache(cache_key)
        if cached is None:
            search_url = (
                "https://www.wikidata.org/w/api.php"
                f"?action=wbsearchentities&search={quote_plus(query)}&language=en&type=item&limit=10&format=json"
            )
            search_payload = await _get_json(search_url)
            ids = [item.get("id") for item in search_payload.get("search", []) if item.get("id")]
            entities_payload: dict[str, Any] = {"entities": {}}
            if ids:
                ids_param = quote_plus("|".join(ids))
                entities_url = (
                    "https://www.wikidata.org/w/api.php"
                    f"?action=wbgetentities&ids={ids_param}&props=labels|descriptions|claims&languages=en&format=json"
                )
                entities_payload = await _get_json(entities_url)
            cached = {"search": search_payload.get("search", []), "entities": entities_payload.get("entities", {})}
            self.database.set_cache(cache_key, cached)

        candidates = []
        for item in cached.get("search", []):
            entity_id = item.get("id")
            entity = cached.get("entities", {}).get(entity_id, {})
            label = ((entity.get("labels") or {}).get("en") or {}).get("value") or item.get("label") or "Unknown"
            description = ((entity.get("descriptions") or {}).get("en") or {}).get("value") or item.get("description") or ""
            if not _looks_like_film(entity, description):
                continue
            candidates.append(
                ShowCandidate(
                    provider="wikidata",
                    provider_id=str(entity_id),
                    title=label,
                    year=_wikidata_release_year(entity) or _year_from_description(description),
                    summary=description[:240],
                )
            )
        return candidates[:10]

    async def _throttle_jikan(self) -> None:
        elapsed = time.monotonic() - self._last_jikan_request
        wait_for = 1.1 - elapsed
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        self._last_jikan_request = time.monotonic()


async def _get_json(url: str) -> Any:
    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "TvSorter/0.1"}) as client:
        for attempt in range(3):
            response = await client.get(url)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            retry_after = response.headers.get("Retry-After")
            wait_for = float(retry_after) if retry_after and retry_after.isdigit() else 2.0 * (attempt + 1)
            await asyncio.sleep(wait_for)
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


def _looks_like_film(entity: dict[str, Any], description: str) -> bool:
    if "film" in description.lower() or "movie" in description.lower():
        return True
    for claim in (entity.get("claims") or {}).get("P31", []):
        value = (((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}).get("id")
        if value in {"Q11424", "Q24862", "Q506240"}:
            return True
    return False


def _wikidata_release_year(entity: dict[str, Any]) -> int | None:
    for claim in (entity.get("claims") or {}).get("P577", []):
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        year = _year_from_date(value.get("time", "").lstrip("+"))
        if year:
            return year
    return None


def _year_from_description(description: str) -> int | None:
    import re

    match = re.search(r"\b((?:19|20)\d{2})\b", description)
    return int(match.group(1)) if match else None
