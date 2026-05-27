# TvSorter Development Tracker

## Standing Rule

Before starting any development task, read:

1. `docs/PRD.md`
2. `DEV.md`

Keep this file updated as implementation progresses. Record completed work, decisions, open questions, and next tasks here.

## Current Status

- Repository initialized.
- Product requirements captured in `docs/PRD.md`.
- Development tracker created in `DEV.md`.
- Initial FastAPI/Jinja application scaffold is implemented.
- SQLite persistence is implemented for settings, input roots, imports, library files, and provider cache.
- Settings, browsing, matching, import, library, history, and output rescan pages exist.
- TVMaze and Jikan provider clients exist with SQLite-backed response caching.
- Core parser, naming, filesystem, and import services have unit tests.
- Proxmox host-side LXC creation script exists in `scripts/create-proxmox-lxc.sh`.

## Confirmed Decisions

- App runs in a privileged LXC container.
- LAN-only UI, no login for MVP.
- Source files remain untouched.
- User chooses hardlink or copy per import.
- Input and output paths are mounted into the LXC.
- TV and Anime have separate manually configured output roots.
- Metadata language is English.
- Use normal season/episode naming for anime and TV.
- Add show year to output paths.
- Ignore subtitles for MVP.
- Use non-login public metadata APIs.
- Default TV provider: TVMaze.
- Default Anime provider: Jikan.
- Film support uses no-login IMDb-style suggestion lookup, then Wikidata, plus filename parsing/manual correction fallback.

## Target Naming Format

```text
TV/Anime:

```text
Show Name (Year)/Season XX/Show Name (Year) - SXXEYY - Episode Name - Quality.ext
```

Film:

```text
Film Name (Year) - Quality.ext
```

## Planned Milestones

### 1. Project Scaffold

- [x] Choose frontend style: server-rendered FastAPI/Jinja with small plain JS.
- [x] Create FastAPI app.
- [x] Add SQLite setup.
- [x] Add basic config loading.
- [x] Add development run command.

### 2. Settings and Persistence

- [x] Add settings schema.
- [x] Add input roots.
- [x] Add TV output root.
- [x] Add Anime output root.
- [x] Add Film output root.
- [x] Add permission checks.

### 3. Filesystem Browser

- [x] Browse configured input roots.
- [x] Prevent path traversal.
- [x] List files and folders.
- [x] Recursively expand selected folders.
- [x] Filter video files.
- [x] Ignore subtitles.

### 4. Parser and Naming

- [x] Parse show title, year, season, episode, and quality from filenames.
- [ ] Add ffprobe fallback for quality if available.
- [x] Generate destination paths.
- [x] Sanitize filesystem names.

### 5. Metadata Providers

- [x] Add provider interface.
- [x] Add TVMaze provider.
- [x] Add Jikan provider.
- [x] Add request cache.
- [x] Add manual override fields in import form.
- [x] Add Film manual metadata path without provider lookup.

### 6. Import Engine

- [x] Implement preview/test mode.
- [x] Implement hardlink action.
- [x] Implement copy action.
- [x] Implement conflict policies: skip, replace, index, fail.
- [x] Persist import results.

### 7. Web UI

- [x] Settings page.
- [x] Input browser.
- [x] Match queue.
- [x] Manual correction UI.
- [x] Sticky browser controls for long folder lists.
- [x] Import result state badges, row colors, and state filters.
- [x] Import preview.
- [x] Library view.
- [x] History/logs view.

### 8. Output Library Rescan

- [x] Scan TV output root.
- [x] Scan Anime output root.
- [x] Reconcile DB records with files on disk.
- [x] Mark missing files.

### 9. LXC Deployment

- [x] Add systemd unit example.
- [x] Add install/run documentation.
- [x] Document mount and permission expectations.
- [x] Add Proxmox host-side LXC creation script.

## Open Questions

- Whether to include Docker/container packaging in addition to LXC/systemd docs.
- Whether to add TMDB/TheTVDB optional API-key providers later.
- Whether to add queue-level bulk controls for very large imports.

## Known Gaps

- ffprobe quality fallback is not implemented yet.
- Manual episode selection is currently done through editable season/episode/title fields; there is not yet a provider episode dropdown.
- Metadata lookup during match is synchronous per selected file, with simple in-process de-duplication and persistent HTTP response cache.
- Jikan episode support currently treats anime as season 1 from returned episode numbers; multi-season anime mapping needs more provider-specific work.

## Development Log

### 2026-05-26

- Created `docs/PRD.md` from the agreed product requirements.
- Created `DEV.md` with standing workflow rule and milestone tracker.
- Implemented initial FastAPI/Jinja application.
- Added SQLite schema and persistence layer.
- Added safe input-root browsing and recursive video expansion.
- Added filename parser and Plex/Jellyfin-style destination naming.
- Added hardlink/copy/test import engine with skip/replace/index/fail conflicts.
- Added TVMaze and Jikan metadata providers with SQLite response cache.
- Added settings, browse, match, preview, import results, library, and history pages.
- Added output library rescan.
- Added development README and LXC deployment documentation.
- Added unit tests for parser, naming, filesystem safety, and import conflict behavior.
- Verified with pytest and browser smoke test against `/tmp/tvsorter-demo`.
- Added `scripts/create-proxmox-lxc.sh` to create a privileged Debian LXC on Proxmox and install TvSorter from GitHub.
- Updated the Proxmox script to default to `--storage auto` because not every node has `local-lvm`.
- Updated the Proxmox script to prompt for root disk and template storage in interactive terminals.
- Added in-container `update` command installation for pulling latest GitHub `main`, refreshing dependencies, and restarting `tvsorter.service`.
- Added Proxmox LXC console autologin via systemd getty overrides during install and update.
- Added Settings folder picker for browsing LXC-mounted folders when selecting input and output roots.
- Expanded autologin coverage to include `console-getty.service` and restart available getty units after applying overrides.
- Added Film media type with separate output root, film parser, film naming, import support, and SQLite migration for existing DBs.
- Added anime-style `E02` parsing, Jikan throttling/retry behavior, batch provider de-duplication, and Wikidata film lookup.
- Changed Film lookup to prefer movie-focused IMDb-style suggestion results before Wikidata, and added Wikimedia API identification headers plus cleaner 401/403 metadata fallback errors.

### 2026-05-27

- Added actionable permission-denied import errors, sticky input browser controls, and import result state coloring/filtering.
- Added `tvsorter-access` helper for shared LXC media mounts so TvSorter can match an existing writable UID/GID or group without changing media folder permissions.
- Added latest import status badges to the input browser for video source files already processed by TvSorter.
- Added Browse status filters, an "Only no status" view, and manual per-source status overrides stored separately from import history.
- Moved status changes to a selected-items browser action, applied status changes recursively to selected folders, made browser rows clickable, and added a persistent dark theme toggle.
- Added a delayed progress indicator for operations that run longer than two seconds and removed the Import Results "Open Library" shortcut.
- Changed Film imports to copy/hardlink directly into the Film output root instead of creating one folder per movie.
- Added background import jobs with real copy progress, current item display, and determinate import percentage polling.
- Hardened long filename/path wrapping in match, preview, and import result views so paths cannot push panels off-screen.
- Fixed Import Results and Preview table column sizing so long source paths cannot squeeze destination/state columns; empty Error columns are hidden when no rows have errors.
