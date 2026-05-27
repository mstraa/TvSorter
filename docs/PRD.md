# TvSorter PRD

## Overview

TvSorter is a LAN-only web application intended to run inside a privileged LXC container. It helps curate TV shows, anime, and films from mounted input folders into clean, Plex/Jellyfin-friendly output libraries without modifying the original files.

The app lets a user browse mounted input folders, select files or folders, identify the show and episode from public metadata sources, manually correct matches when needed, then hardlink or copy the selected media into a curated output folder using a consistent naming structure.

## Goals

- Provide a web UI for manually controlled TV/anime/film imports.
- Keep source files untouched.
- Allow per-import choice between hardlink and copy.
- Support separate manually configured output roots for TV, Anime, and Film.
- Persist imported library state across app restarts.
- Allow users to see already imported files from the output folders.
- Use non-login public metadata APIs.
- Use English metadata.
- Support normal season/episode naming for anime and TV.
- Ignore subtitles for the MVP.

## Non-Goals

- No automatic deletion, moving, or renaming of source files.
- No user login or authentication in the MVP.
- No subtitle import in the MVP.
- Film support starts with filename parsing and manual correction. Public no-login film metadata is not required for the MVP.
- No automatic daemon-style watch/import workflow in the MVP.
- No dependency on paid or logged-in metadata APIs in the MVP.

## Runtime Environment

- Runs inside a privileged LXC container.
- Input and output folders are mounted into the LXC by the host.
- The web app is available only on the LAN.
- The app process should run as a non-root user where possible.
- Hardlinks only work when source and destination are on the same filesystem/device. If hardlinking fails, the UI must explain the failure and let the user copy instead.

## Recommended Stack

- Backend: Python FastAPI
- Database: SQLite
- Frontend: simple web UI, either server-rendered templates/HTMX or React
- Optional media inspection: ffprobe
- Service management: systemd inside the LXC

## Metadata Providers

### TV

Use TVMaze public API by default.

- No login/API key required.
- Supports show search and episode data.
- English metadata is preferred.

### Anime

Use Jikan public API by default.

- No login/API key required.
- Based on public MyAnimeList data.
- Use normal season/episode naming in TvSorter even for anime.

### Film

Use a no-login film lookup chain plus filename parsing/manual correction by default.

- No logged/API-key provider is required for the MVP.
- Film lookup should try IMDb-style public suggestion results first for title/year candidates.
- Wikidata should remain a fallback and should be queried with a descriptive API user agent.
- Optional API-key providers may be added later for richer film metadata.

### Future Optional Providers

These may be added later if API keys are acceptable:

- TMDB
- TheTVDB
- AniList

## User Configuration

The Settings UI must allow configuring:

- One or more input roots.
- One TV output root.
- One Anime output root.
- One Film output root.

Example:

```text
Input roots:
- /mnt/downloads
- /mnt/incoming

TV output root:
- /mnt/media/TV

Anime output root:
- /mnt/media/Anime

Film output root:
- /mnt/media/Films
```

## Import Workflow

1. User opens the web UI.
2. User selects an input root.
3. App shows files and folders under that root.
4. User selects one or more files or folders.
5. If folders are selected, the app recursively expands them into video files.
6. App ignores subtitle files and non-video files.
7. User chooses media type: TV, Anime, or Film.
8. App parses each video filename for:
   - show title
   - year when present
   - season number
   - episode number
   - quality
9. App searches the matching metadata provider when available:
   - TVMaze for TV
   - Jikan for Anime
   - IMDb-style suggestion search, then Wikidata fallback for Film
10. App shows proposed matches.
11. User may manually override:
   - provider result
   - show title
   - show year
   - season number, episode number, and episode title for TV/Anime
   - title and year for Film
   - quality
12. App previews final destination paths.
13. User chooses hardlink or copy per import.
14. If a destination file already exists, user chooses a conflict policy.
15. App performs the import.
16. App records the import in SQLite.
17. App shows the imported item in library/history views.

## Naming Format

TV and Anime use the same structure, but under separate output roots.

```text
Show Name (Year)/Season XX/Show Name (Year) - SXXEYY - Episode Name - Quality.ext
```

Example:

```text
/mnt/media/TV/Fringe (2008)/Season 01/Fringe (2008) - S01E01 - Pilot - 1080p.mkv
```

Anime example:

```text
/mnt/media/Anime/Cowboy Bebop (1998)/Season 01/Cowboy Bebop (1998) - S01E01 - Asteroid Blues - 1080p.mkv
```

Film uses a movie-style structure under the Film output root.

```text
Film Name (Year)/Film Name (Year) - Quality.ext
```

Film example:

```text
/mnt/media/Films/Blade Runner 2049 (2017)/Blade Runner 2049 (2017) - 2160p.mkv
```

## Quality Detection

Quality should be detected in this order:

1. Filename tags such as `720p`, `1080p`, or `2160p`.
2. ffprobe resolution fallback if available.
3. `Unknown` when quality cannot be determined.

## Rate Limiting

Provider calls should be cached and de-duplicated during batch matching.

- Jikan requests should be throttled to avoid `429 Too Many Requests`.
- Repeated files from the same show should reuse one show search and one episode-list lookup.
- Film lookup should prefer a movie-focused provider before generic knowledge-base lookup.
- If a provider still rate-limits or fails, the UI should keep the filename-parsed fallback available for manual correction.

## Import Actions

The user chooses the action per import:

- `hardlink`
- `copy`
- `test` or preview-only, for dry runs

Source files must remain untouched regardless of action.

## Conflict Handling

If the destination already exists, support FileBot-style conflict modes:

- `skip`: leave existing file untouched and do not import this item.
- `replace`: overwrite the existing output file.
- `index`: keep both files by adding a suffix such as `(2)`.
- `fail`: stop and show an error.

Default conflict policy: `skip`.

## Persistence

SQLite must store app settings, import history, and library state.

Each import should record:

- source path
- source size
- source mtime
- source device and inode when available
- output path
- media type: TV, Anime, or Film
- metadata provider
- provider show ID
- show title
- show year
- season number
- episode number
- episode title
- detected quality
- selected action: hardlink or copy
- conflict policy
- import result
- imported timestamp

The app should also offer an output rescan action so files added, removed, or changed outside the app can be reflected after restart or manual maintenance.

## Web UI Pages

### Settings

- Configure input roots.
- Configure TV output root.
- Configure Anime output root.
- Configure Film output root.
- Show basic permission/read-write checks.

### Input Browser

- Browse configured input roots.
- Show files and folders.
- Select one or more files/folders.
- Expand selected folders recursively into video files.
- Keep root/type/action controls visible while scrolling long folders.

### Match Queue

- Show parsed filename data.
- Show metadata search results.
- Allow manual match correction.
- Allow media type selection.
- Allow quality correction.

### Import Preview

- Show source path.
- Show destination path.
- Show selected action.
- Show conflict status.
- Allow final validation before import.

### Import Results

- Show a clear state for each attempted import.
- Color rows by state so failed, skipped, preview, conflict, and imported rows are easy to scan.
- Allow filtering visible rows by state.
- Show permission failures with actionable output-mount guidance.

### Library

- Show already imported files.
- Group by TV/Anime/Film, show or film title, season, and episode where applicable.
- Indicate whether files are present on disk.
- Provide output rescan action.

### History/Logs

- Show completed imports.
- Show skipped imports.
- Show failed imports and error messages.

## Database Model

Initial tables:

- `settings`
- `input_roots`
- `media_items`
- `shows`
- `episodes`
- `imports`
- `library_files`
- `provider_cache`

The exact schema may evolve during implementation, but the stored data must support restart-safe import history and output folder rescan.

## Safety Requirements

- All file browsing must be constrained to configured input roots.
- Output writes must be constrained to configured TV/Anime/Film output roots.
- Path traversal must be prevented.
- The app must never mutate source files.
- Existing output files must never be overwritten without an explicit user conflict choice.
- Hardlink failures must not silently fall back to copy unless the user chose copy or confirmed fallback.

## References

The product should borrow concepts from:

- FileBot: action selection, conflict modes, manual query override, preview/test behavior.
- mnamer: Python-oriented parsing, provider abstraction, configurable formats, no-overwrite behavior, cache/test workflow.
