from __future__ import annotations

from pathlib import Path

from tvsorter.db import Database
from tvsorter.filesystem import VIDEO_EXTENSIONS


def rescan_outputs(database: Database, roots: dict[str, Path]) -> dict[str, int]:
    counts = {media_type: 0 for media_type in roots}
    for media_type, root in roots.items():
        if not root or not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                database.upsert_discovered_file(media_type, path.resolve())
                counts[media_type] += 1
    database.mark_missing_outside(roots)
    return counts
