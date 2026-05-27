from __future__ import annotations

from pathlib import Path
from typing import Annotated

import uvicorn
import httpx
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tvsorter.config import load_config
from tvsorter.db import Database
from tvsorter.filesystem import expand_video_files, is_relative_to, list_directory
from tvsorter.importer import ImportRequest, ImportResult, execute_import, preview_import, result_to_record
from tvsorter.library import rescan_outputs
from tvsorter.naming import destination_path, film_destination_path
from tvsorter.parser import parse_film_filename, parse_media_filename
from tvsorter.providers import MetadataProviders


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG = load_config()
DATABASE = Database(CONFIG.database_path)
PROVIDERS = MetadataProviders(DATABASE)
PICKER_ROOTS = [Path("/mnt"), Path("/media"), Path("/srv"), Path("/opt"), Path("/var/lib"), Path("/")]
MEDIA_TYPES = {"tv", "anime", "film"}
SOURCE_STATUSES = {"none", "imported", "failed", "skipped", "preview", "conflict"}

app = FastAPI(title="TvSorter")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def startup() -> None:
    DATABASE.init()


@app.get("/", response_class=HTMLResponse)
def index() -> RedirectResponse:
    return RedirectResponse(url="/browse", status_code=303)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    roots = DATABASE.list_input_roots()
    checks = _settings_checks(roots, _output_roots())
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "input_roots_text": "\n".join(row["path"] for row in roots),
            "tv_output_root": DATABASE.get_setting("tv_output_root", ""),
            "anime_output_root": DATABASE.get_setting("anime_output_root", ""),
            "film_output_root": DATABASE.get_setting("film_output_root", ""),
            "checks": checks,
        },
    )


@app.post("/settings")
def save_settings(
    input_roots: Annotated[str, Form()],
    tv_output_root: Annotated[str, Form()] = "",
    anime_output_root: Annotated[str, Form()] = "",
    film_output_root: Annotated[str, Form()] = "",
) -> RedirectResponse:
    roots = [_normalize_path(line) for line in input_roots.splitlines() if line.strip()]
    DATABASE.replace_input_roots(roots)
    DATABASE.set_setting("tv_output_root", _normalize_path(tv_output_root) if tv_output_root.strip() else "")
    DATABASE.set_setting(
        "anime_output_root", _normalize_path(anime_output_root) if anime_output_root.strip() else ""
    )
    DATABASE.set_setting("film_output_root", _normalize_path(film_output_root) if film_output_root.strip() else "")
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/browse", response_class=HTMLResponse)
def browse_page(
    request: Request,
    root_id: int | None = Query(default=None),
    path: str = Query(default=""),
) -> HTMLResponse:
    roots = DATABASE.list_input_roots()
    active_root = DATABASE.get_input_root(root_id) if root_id else (roots[0] if roots else None)
    entries = []
    error = None
    parent_path = ""
    if active_root:
        try:
            entries = list_directory(Path(active_root["path"]), path)
            video_sources = [entry.absolute_path for entry in entries if entry.is_video]
            imports_by_source = DATABASE.latest_imports_for_sources(video_sources)
            overrides_by_source = DATABASE.source_status_overrides(video_sources)
            entries = [_with_browse_status(entry, imports_by_source, overrides_by_source) for entry in entries]
            parent_path = _parent_relative(path)
        except (OSError, ValueError) as exc:
            error = str(exc)
    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "roots": roots,
            "active_root": active_root,
            "current_path": path,
            "parent_path": parent_path,
            "entries": entries,
            "error": error,
        },
    )


@app.post("/match", response_class=HTMLResponse)
async def match_page(
    request: Request,
    root_id: Annotated[int, Form()],
    media_type: Annotated[str, Form()],
    selected: Annotated[list[str] | None, Form()] = None,
) -> HTMLResponse:
    root = DATABASE.get_input_root(root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Input root not found")
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Invalid media type")

    files = expand_video_files(Path(root["path"]), selected or [])
    rows = []
    provider_cache: dict[str, object] = {}
    episode_cache: dict[tuple[str, str], object] = {}
    match_cache: dict[tuple[str, str, int | None], dict] = {}
    for file_path in files:
        parsed = parse_film_filename(file_path) if media_type == "film" else parse_media_filename(file_path)
        if media_type == "film":
            cache_key = (media_type, getattr(parsed, "title").casefold(), getattr(parsed, "year"))
            enriched = match_cache.get(cache_key)
            if enriched is None:
                enriched = await _enrich_film_match(parsed, provider_cache)
                match_cache[cache_key] = enriched
        else:
            enriched = await _enrich_match(parsed, media_type, provider_cache, episode_cache)
        rows.append({"source_path": file_path, "parsed": parsed, **enriched})

    return templates.TemplateResponse(
        request,
        "match.html",
        {
            "media_type": media_type,
            "rows": rows,
            "action": "hardlink",
            "conflict_policy": "skip",
            "output_root": _output_roots().get(media_type),
        },
    )


@app.post("/imports", response_class=HTMLResponse)
def run_imports(
    request: Request,
    media_type: Annotated[str, Form()],
    action: Annotated[str, Form()],
    conflict_policy: Annotated[str, Form()],
    source_path: Annotated[list[str], Form()],
    show_title: Annotated[list[str], Form()],
    show_year: Annotated[list[str], Form()],
    season_number: Annotated[list[int], Form()],
    episode_number: Annotated[list[int], Form()],
    episode_title: Annotated[list[str], Form()],
    quality: Annotated[list[str], Form()],
    provider: Annotated[list[str], Form()],
    provider_show_id: Annotated[list[str], Form()],
) -> HTMLResponse:
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Invalid media type")
    if action not in {"hardlink", "copy", "test"}:
        raise HTTPException(status_code=400, detail="Invalid action")
    if conflict_policy not in {"skip", "replace", "index", "fail"}:
        raise HTTPException(status_code=400, detail="Invalid conflict policy")
    output_root = _output_roots().get(media_type)
    if not output_root:
        raise HTTPException(status_code=400, detail=f"No {media_type} output root configured")

    results = []
    for index, source in enumerate(source_path):
        source_file = Path(source).resolve()
        _assert_source_allowed(source_file)
        request_model = ImportRequest(
            source_path=source_file,
            output_root=output_root,
            media_type=media_type,
            show_title=show_title[index],
            show_year=_optional_int(show_year[index]),
            season_number=season_number[index],
            episode_number=episode_number[index],
            episode_title=episode_title[index],
            quality=quality[index],
            action=action,
            conflict_policy=conflict_policy,
            provider=provider[index] or None,
            provider_show_id=provider_show_id[index] or None,
        )
        result = execute_import(request_model)
        DATABASE.insert_import(result_to_record(result))
        results.append(result)

    return templates.TemplateResponse(request, "import_results.html", {"results": results})


@app.post("/preview", response_class=HTMLResponse)
def preview_imports(
    request: Request,
    media_type: Annotated[str, Form()],
    action: Annotated[str, Form()],
    conflict_policy: Annotated[str, Form()],
    source_path: Annotated[list[str], Form()],
    show_title: Annotated[list[str], Form()],
    show_year: Annotated[list[str], Form()],
    season_number: Annotated[list[int], Form()],
    episode_number: Annotated[list[int], Form()],
    episode_title: Annotated[list[str], Form()],
    quality: Annotated[list[str], Form()],
    provider: Annotated[list[str], Form()],
    provider_show_id: Annotated[list[str], Form()],
) -> HTMLResponse:
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Invalid media type")
    output_root = _output_roots().get(media_type)
    if not output_root:
        raise HTTPException(status_code=400, detail=f"No {media_type} output root configured")
    results = []
    for index, source in enumerate(source_path):
        source_file = Path(source).resolve()
        _assert_source_allowed(source_file)
        import_request = ImportRequest(
            source_path=source_file,
            output_root=output_root,
            media_type=media_type,
            show_title=show_title[index],
            show_year=_optional_int(show_year[index]),
            season_number=season_number[index],
            episode_number=episode_number[index],
            episode_title=episode_title[index],
            quality=quality[index],
            action=action,
            conflict_policy=conflict_policy,
            provider=provider[index] or None,
            provider_show_id=provider_show_id[index] or None,
        )
        try:
            result = preview_import(import_request)
        except (FileExistsError, ValueError) as exc:
            if media_type == "film":
                output_path = film_destination_path(
                    output_root=output_root,
                    title=import_request.show_title,
                    year=import_request.show_year,
                    quality=import_request.quality,
                    source_path=import_request.source_path,
                )
            else:
                output_path = destination_path(
                    output_root=output_root,
                    title=import_request.show_title,
                    year=import_request.show_year,
                    season=import_request.season_number,
                    episode=import_request.episode_number,
                    episode_title=import_request.episode_title,
                    quality=import_request.quality,
                    source_path=import_request.source_path,
                )
            result = ImportResult(import_request, output_path, output_path, "failed", str(exc))
        results.append(result)
    return templates.TemplateResponse(request, "preview.html", {"results": results})


@app.get("/library", response_class=HTMLResponse)
def library_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "library.html",
        {"files": DATABASE.list_library_files(), "roots": _output_roots()},
    )


@app.post("/library/rescan")
def rescan_library() -> RedirectResponse:
    rescan_outputs(DATABASE, _output_roots())
    return RedirectResponse(url="/library", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "history.html", {"imports": DATABASE.list_imports()})


@app.get("/api/search")
async def api_search(media_type: str, q: str) -> dict[str, object]:
    return {"results": [candidate.__dict__ for candidate in await PROVIDERS.search(media_type, q)]}


@app.get("/api/episodes")
async def api_episodes(media_type: str, provider_show_id: str) -> dict[str, object]:
    return {
        "results": [
            candidate.__dict__
            for candidate in await PROVIDERS.episodes(media_type, provider_show_id)
        ]
    }


@app.post("/api/source-status")
def api_source_status(
    source_path: Annotated[str, Form()],
    status: Annotated[str, Form()],
) -> dict[str, object]:
    source = Path(source_path).resolve()
    _assert_source_allowed(source)
    if status == "auto":
        DATABASE.set_source_status_override(source, None)
        return {"status": "auto"}
    if status not in SOURCE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    DATABASE.set_source_status_override(source, status)
    return {"status": status}


@app.get("/api/folders")
def api_folders(path: str = Query(default="/")) -> dict[str, object]:
    current_path = _resolve_picker_path(path)
    folders = []
    try:
        children = sorted(
            [child for child in current_path.iterdir() if child.is_dir()],
            key=lambda item: item.name.lower(),
        )
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for child in children:
        try:
            child.stat()
        except OSError:
            continue
        folders.append({"name": child.name, "path": str(child)})

    parent = current_path.parent if current_path != current_path.parent else None
    return {
        "path": str(current_path),
        "parent": str(parent) if parent else None,
        "folders": folders,
        "roots": [str(root) for root in PICKER_ROOTS if root.exists()],
    }


def run() -> None:
    uvicorn.run("tvsorter.main:app", host=CONFIG.host, port=CONFIG.port, reload=False)


async def _enrich_match(parsed: object, media_type: str, search_cache: dict, episode_cache: dict) -> dict:
    title = getattr(parsed, "title")
    fallback = {
        "show_title": title,
        "show_year": getattr(parsed, "year"),
        "episode_title": getattr(parsed, "episode_title"),
        "provider": "",
        "provider_show_id": "",
        "candidates": [],
        "metadata_error": None,
    }
    try:
        candidates = search_cache.get(title)
        if candidates is None:
            candidates = await PROVIDERS.search(media_type, title)
            search_cache[title] = candidates
        if not candidates:
            return fallback | {"candidates": []}
        selected = candidates[0]
        episode_key = (media_type, selected.provider_id)
        episodes = episode_cache.get(episode_key)
        if episodes is None:
            episodes = await PROVIDERS.episodes(media_type, selected.provider_id)
            episode_cache[episode_key] = episodes
        episode_title = getattr(parsed, "episode_title")
        for episode in episodes:
            if (
                episode.season == getattr(parsed, "season")
                and episode.episode == getattr(parsed, "episode")
            ):
                episode_title = episode.title
                break
        return {
            "show_title": selected.title,
            "show_year": selected.year or getattr(parsed, "year"),
            "episode_title": episode_title,
            "provider": selected.provider,
            "provider_show_id": selected.provider_id,
            "candidates": candidates,
            "metadata_error": None,
        }
    except Exception as exc:
        return fallback | {"metadata_error": _metadata_error_message(exc)}


def _output_roots() -> dict[str, Path]:
    roots = {}
    tv_root = DATABASE.get_setting("tv_output_root", "")
    anime_root = DATABASE.get_setting("anime_output_root", "")
    film_root = DATABASE.get_setting("film_output_root", "")
    if tv_root:
        roots["tv"] = Path(tv_root)
    if anime_root:
        roots["anime"] = Path(anime_root)
    if film_root:
        roots["film"] = Path(film_root)
    return roots


async def _enrich_film_match(parsed: object, search_cache: dict) -> dict:
    fallback = {
        "show_title": getattr(parsed, "title"),
        "show_year": getattr(parsed, "year"),
        "episode_title": "Film",
        "provider": "",
        "provider_show_id": "",
        "candidates": [],
        "metadata_error": None,
    }
    title = getattr(parsed, "title")
    try:
        candidates = search_cache.get(title)
        if candidates is None:
            candidates = await PROVIDERS.search("film", title)
            search_cache[title] = candidates
        if not candidates:
            return fallback
        parsed_year = getattr(parsed, "year")
        selected = next(
            (candidate for candidate in candidates if parsed_year and candidate.year == parsed_year),
            candidates[0],
        )
        return {
            "show_title": selected.title,
            "show_year": selected.year or getattr(parsed, "year"),
            "episode_title": "Film",
            "provider": selected.provider,
            "provider_show_id": selected.provider_id,
            "candidates": candidates,
            "metadata_error": None,
        }
    except Exception as exc:
        return fallback | {"metadata_error": _metadata_error_message(exc)}


def _metadata_error_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 429:
            return "Metadata provider is rate-limiting requests. Filename parsing was used for this item."
        if exc.response.status_code in {401, 403}:
            return "Metadata provider refused the request. Filename parsing was used for this item."
    return str(exc)


def _with_browse_status(
    entry: object,
    imports_by_source: dict[str, object],
    overrides_by_source: dict[str, object],
) -> dict[str, object]:
    status = None
    latest_import = None
    override = None
    if getattr(entry, "is_video"):
        source_key = str(getattr(entry, "absolute_path").resolve())
        override = overrides_by_source.get(source_key)
        latest_import = imports_by_source.get(source_key)
        if override:
            status = None if override["status"] == "none" else override["status"]
        elif latest_import:
            status = latest_import["result"]
    manual_status = override["status"] if override else "auto"
    status_key = status or "none"
    return {
        "entry": entry,
        "status": status,
        "status_key": status_key,
        "manual_status": manual_status,
        "latest_import": latest_import,
    }


def _settings_checks(input_roots: list, output_roots: dict[str, Path]) -> list[dict[str, object]]:
    checks = []
    for row in input_roots:
        path = Path(row["path"])
        checks.append({"label": f"Input: {path}", "exists": path.exists(), "read": path.is_dir() and os_access(path, "read")})
    for media_type, path in output_roots.items():
        checks.append(
            {
                "label": f"{media_type.title()} output: {path}",
                "exists": path.exists(),
                "read": path.is_dir() and os_access(path, "read"),
                "write": path.is_dir() and os_access(path, "write"),
            }
        )
    return checks


def os_access(path: Path, mode: str) -> bool:
    import os

    return os.access(path, os.R_OK if mode == "read" else os.W_OK)


def _normalize_path(value: str) -> str:
    return str(Path(value.strip()).expanduser().resolve())


def _parent_relative(path: str) -> str:
    if not path:
        return ""
    parent = str(Path(path).parent)
    return "" if parent == "." else parent


def _optional_int(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def _assert_source_allowed(source_path: Path) -> None:
    roots = [Path(row["path"]) for row in DATABASE.list_input_roots()]
    if not any(is_relative_to(source_path, root) for root in roots):
        raise HTTPException(status_code=400, detail=f"Source is outside configured input roots: {source_path}")


def _resolve_picker_path(value: str) -> Path:
    path = Path(value or "/").expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Folder does not exist: {path}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a folder: {path}")
    return path
