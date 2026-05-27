from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
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
from tvsorter.filesystem import expand_source_files, expand_video_files, is_relative_to, list_directory
from tvsorter.formatting import human_file_size
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
BROWSE_STATUS_KEYS = SOURCE_STATUSES | {"cancelled", "mixed"}
ASSET_VERSION = str(
    max(
        int((BASE_DIR / "static" / "app.css").stat().st_mtime),
        int((BASE_DIR / "static" / "app.js").stat().st_mtime),
    )
)


@dataclass
class ImportJob:
    id: str
    requests: list[ImportRequest]
    total_units: int
    completed_units: int = 0
    completed_items: int = 0
    current_item_index: int = 0
    current_item: str = ""
    current_action: str = ""
    current_item_bytes: int = 0
    current_item_total: int = 0
    state: str = "running"
    cancel_requested: bool = False
    results: list[ImportResult] = field(default_factory=list)
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            percent = 100 if self.total_units <= 0 else int(min(100, (self.completed_units / self.total_units) * 100))
            item_percent = (
                0
                if self.current_item_total <= 0
                else int(min(100, (self.current_item_bytes / self.current_item_total) * 100))
            )
            return {
                "id": self.id,
                "state": self.state,
                "percent": percent,
                "current_item": self.current_item,
                "current_action": self.current_action,
                "current_item_index": self.current_item_index,
                "current_item_bytes": self.current_item_bytes,
                "current_item_total": self.current_item_total,
                "current_item_percent": item_percent,
                "completed": self.completed_units,
                "total": self.total_units,
                "completed_items": self.completed_items,
                "total_items": len(self.requests),
                "cancel_requested": self.cancel_requested,
                "error": self.error,
            }


IMPORT_JOBS: dict[str, ImportJob] = {}
IMPORT_JOBS_LOCK = threading.Lock()

app = FastAPI(title="TvSorter")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["asset_version"] = ASSET_VERSION
templates.env.filters["filesize"] = human_file_size
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
            "copy_rate_limit_mbps": DATABASE.get_setting("copy_rate_limit_mbps", "15"),
            "checks": checks,
        },
    )


@app.post("/settings")
def save_settings(
    input_roots: Annotated[str, Form()],
    tv_output_root: Annotated[str, Form()] = "",
    anime_output_root: Annotated[str, Form()] = "",
    film_output_root: Annotated[str, Form()] = "",
    copy_rate_limit_mbps: Annotated[str, Form()] = "15",
) -> RedirectResponse:
    roots = [_normalize_path(line) for line in input_roots.splitlines() if line.strip()]
    DATABASE.replace_input_roots(roots)
    DATABASE.set_setting("tv_output_root", _normalize_path(tv_output_root) if tv_output_root.strip() else "")
    DATABASE.set_setting(
        "anime_output_root", _normalize_path(anime_output_root) if anime_output_root.strip() else ""
    )
    DATABASE.set_setting("film_output_root", _normalize_path(film_output_root) if film_output_root.strip() else "")
    DATABASE.set_setting("copy_rate_limit_mbps", _normalize_copy_rate_limit(copy_rate_limit_mbps))
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
            entry_sources = _browse_entry_sources(Path(active_root["path"]), entries)
            video_sources = sorted({source for sources in entry_sources.values() for source in sources})
            imports_by_source = DATABASE.latest_imports_for_sources(video_sources)
            overrides_by_source = DATABASE.source_status_overrides(video_sources)
            entries = [
                _with_browse_status(entry, entry_sources.get(entry.relative_path, []), imports_by_source, overrides_by_source)
                for entry in entries
            ]
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
    import_requests = _build_import_requests(
        media_type=media_type,
        action=action,
        conflict_policy=conflict_policy,
        source_path=source_path,
        show_title=show_title,
        show_year=show_year,
        season_number=season_number,
        episode_number=episode_number,
        episode_title=episode_title,
        quality=quality,
        provider=provider,
        provider_show_id=provider_show_id,
    )
    results = []
    copy_rate_limit_mbps = _copy_rate_limit_mbps()
    for request_model in import_requests:
        result = execute_import(request_model, copy_rate_limit_mbps=copy_rate_limit_mbps)
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
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Invalid media type")
    query = q.strip()
    if not query:
        return {"results": []}
    return {"results": [candidate.__dict__ for candidate in await PROVIDERS.search(media_type, query)]}


@app.get("/api/episodes")
async def api_episodes(media_type: str, provider_show_id: str) -> dict[str, object]:
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Invalid media type")
    return {
        "results": [
            candidate.__dict__
            for candidate in await PROVIDERS.episodes(media_type, provider_show_id)
        ]
    }


@app.post("/api/source-status")
def api_source_status(
    status: Annotated[str, Form()],
    root_id: Annotated[int | None, Form()] = None,
    selected: Annotated[list[str] | None, Form()] = None,
    source_path: Annotated[str | None, Form()] = None,
) -> dict[str, object]:
    sources = _status_update_sources(root_id, selected, source_path)
    if not sources:
        raise HTTPException(status_code=400, detail="No files selected")
    if status == "auto":
        DATABASE.set_source_status_overrides(sources, None)
        return {"status": "auto", "updated": len(sources)}
    if status not in SOURCE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    DATABASE.set_source_status_overrides(sources, status)
    return {"status": status, "updated": len(sources)}


@app.post("/api/import-jobs")
async def api_start_import_job(request: Request) -> dict[str, object]:
    form = await request.form()
    import_requests = _build_import_requests(
        media_type=str(form.get("media_type", "")),
        action=str(form.get("action", "")),
        conflict_policy=str(form.get("conflict_policy", "")),
        source_path=[str(value) for value in form.getlist("source_path")],
        show_title=[str(value) for value in form.getlist("show_title")],
        show_year=[str(value) for value in form.getlist("show_year")],
        season_number=[int(value) for value in form.getlist("season_number")],
        episode_number=[int(value) for value in form.getlist("episode_number")],
        episode_title=[str(value) for value in form.getlist("episode_title")],
        quality=[str(value) for value in form.getlist("quality")],
        provider=[str(value) for value in form.getlist("provider")],
        provider_show_id=[str(value) for value in form.getlist("provider_show_id")],
    )
    job = ImportJob(
        id=uuid.uuid4().hex,
        requests=import_requests,
        total_units=sum(_import_request_units(import_request) for import_request in import_requests),
    )
    with IMPORT_JOBS_LOCK:
        IMPORT_JOBS[job.id] = job
    threading.Thread(target=_run_import_job, args=(job, _copy_rate_limit_mbps()), daemon=True).start()
    return job.snapshot()


@app.get("/api/import-jobs/{job_id}")
def api_import_job(job_id: str) -> dict[str, object]:
    return _get_import_job(job_id).snapshot()


@app.post("/api/import-jobs/{job_id}/cancel")
def api_cancel_import_job(job_id: str) -> dict[str, object]:
    job = _get_import_job(job_id)
    with job.lock:
        if job.state == "running":
            job.cancel_requested = True
    return job.snapshot()


@app.get("/import-jobs/{job_id}/results", response_class=HTMLResponse)
def import_job_results(request: Request, job_id: str) -> HTMLResponse:
    job = _get_import_job(job_id)
    if job.state not in {"done", "cancelled"}:
        raise HTTPException(status_code=409, detail="Import job is not done")
    return templates.TemplateResponse(request, "import_results.html", {"results": job.results})


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


def _build_import_requests(
    media_type: str,
    action: str,
    conflict_policy: str,
    source_path: list[str],
    show_title: list[str],
    show_year: list[str],
    season_number: list[int],
    episode_number: list[int],
    episode_title: list[str],
    quality: list[str],
    provider: list[str],
    provider_show_id: list[str],
) -> list[ImportRequest]:
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Invalid media type")
    if action not in {"hardlink", "copy", "test"}:
        raise HTTPException(status_code=400, detail="Invalid action")
    if conflict_policy not in {"skip", "replace", "index", "fail"}:
        raise HTTPException(status_code=400, detail="Invalid conflict policy")
    output_root = _output_roots().get(media_type)
    if not output_root:
        raise HTTPException(status_code=400, detail=f"No {media_type} output root configured")

    requests = []
    for index, source in enumerate(source_path):
        source_file = Path(source).resolve()
        _assert_source_allowed(source_file)
        requests.append(
            ImportRequest(
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
        )
    return requests


def _run_import_job(job: ImportJob, copy_rate_limit_mbps: float | None = None) -> None:
    try:
        for index, import_request in enumerate(job.requests, start=1):
            with job.lock:
                if job.cancel_requested:
                    job.state = "cancelled"
                    break
                item_start = job.completed_units
                job.current_item_index = index
                job.current_item = import_request.source_path.name
                job.current_action = import_request.action
                job.current_item_bytes = 0
                job.current_item_total = _import_request_units(import_request)
            item_units = _import_request_units(import_request)

            def update_item_progress(copied: int, total: int) -> None:
                with job.lock:
                    job.current_item_bytes = copied
                    job.current_item_total = total
                    if total <= 0:
                        job.completed_units = item_start + item_units
                        return
                    job.completed_units = item_start + int((copied / total) * item_units)

            result = execute_import(
                import_request,
                progress_callback=update_item_progress,
                copy_rate_limit_mbps=copy_rate_limit_mbps,
                cancellation_callback=lambda: _job_cancel_requested(job),
            )
            DATABASE.insert_import(result_to_record(result))
            with job.lock:
                job.results.append(result)
                if result.result != "cancelled":
                    job.completed_items = index
                    job.current_item_bytes = job.current_item_total
                    job.completed_units = item_start + item_units
                else:
                    job.cancel_requested = True
                    job.state = "cancelled"
                    break
        with job.lock:
            job.current_item = ""
            job.current_action = ""
            job.current_item_index = 0
            job.current_item_bytes = 0
            job.current_item_total = 0
            if job.state != "cancelled":
                job.completed_units = job.total_units
                job.state = "done"
    except Exception as exc:
        with job.lock:
            job.error = str(exc)
            job.state = "failed"


def _job_cancel_requested(job: ImportJob) -> bool:
    with job.lock:
        return job.cancel_requested


def _import_request_units(import_request: ImportRequest) -> int:
    if import_request.action == "copy":
        try:
            return max(1, import_request.source_path.stat().st_size)
        except OSError:
            return 1
    return 1


def _copy_rate_limit_mbps() -> float | None:
    value = DATABASE.get_setting("copy_rate_limit_mbps", "15")
    try:
        limit = float(value or 0)
    except ValueError:
        return 15.0
    return limit if limit > 0 else None


def _normalize_copy_rate_limit(value: str) -> str:
    try:
        limit = float(value.replace(",", ".").strip() or 0)
    except ValueError:
        limit = 15.0
    limit = max(0.0, min(limit, 1000.0))
    return str(int(limit)) if limit.is_integer() else f"{limit:.2f}".rstrip("0").rstrip(".")


def _get_import_job(job_id: str) -> ImportJob:
    with IMPORT_JOBS_LOCK:
        job = IMPORT_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


def _browse_entry_sources(root: Path, entries: list[object]) -> dict[str, list[Path]]:
    sources = {}
    for entry in entries:
        if getattr(entry, "is_dir"):
            sources[getattr(entry, "relative_path")] = expand_source_files(root, [getattr(entry, "relative_path")])
        else:
            sources[getattr(entry, "relative_path")] = [getattr(entry, "absolute_path").resolve()]
    return sources


def _with_browse_status(
    entry: object,
    sources: list[Path],
    imports_by_source: dict[str, object],
    overrides_by_source: dict[str, object],
) -> dict[str, object]:
    source_states = [_source_status_for_path(source, imports_by_source, overrides_by_source) for source in sources]
    statuses = {state["status_key"] for state in source_states}
    if not source_states or statuses == {"none"}:
        status = None
        status_key = "none"
    elif len(statuses) == 1:
        status_key = statuses.pop()
        status = None if status_key == "none" else status_key
    else:
        status = "mixed"
        status_key = "mixed"
    latest_import = source_states[0]["latest_import"] if len(source_states) == 1 else None
    manual_status = source_states[0]["manual_status"] if len(source_states) == 1 else ""
    if len({state["manual_status"] for state in source_states}) > 1:
        manual_status = ""
    return {
        "entry": entry,
        "status": status,
        "status_key": status_key,
        "manual_status": manual_status,
        "latest_import": latest_import,
        "source_count": len(source_states),
    }


def _source_status_for_path(
    source: Path,
    imports_by_source: dict[str, object],
    overrides_by_source: dict[str, object],
) -> dict[str, object]:
    source_key = str(source.resolve())
    override = overrides_by_source.get(source_key)
    latest_import = imports_by_source.get(source_key)
    status = None
    if override:
        status = None if override["status"] == "none" else override["status"]
    elif latest_import:
        status = latest_import["result"]
    manual_status = override["status"] if override else "auto"
    status_key = status or "none"
    return {
        "status": status,
        "status_key": status_key,
        "manual_status": manual_status,
        "latest_import": latest_import,
    }


def _status_update_sources(
    root_id: int | None,
    selected: list[str] | None,
    source_path: str | None,
) -> list[Path]:
    if source_path:
        source = Path(source_path).resolve()
        _assert_source_allowed(source)
        return [source]
    if root_id is None:
        raise HTTPException(status_code=400, detail="Input root is required")
    root = DATABASE.get_input_root(root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Input root not found")
    return expand_source_files(Path(root["path"]), selected or [])


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
