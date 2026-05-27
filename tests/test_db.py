from pathlib import Path

import sqlite3

from tvsorter.db import Database


def test_database_migrates_media_type_checks_for_film(tmp_path: Path) -> None:
    db_path = tmp_path / "tvsorter.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            source_size INTEGER,
            source_mtime REAL,
            source_device INTEGER,
            source_inode INTEGER,
            output_path TEXT NOT NULL,
            media_type TEXT NOT NULL CHECK (media_type IN ('tv', 'anime')),
            provider TEXT,
            provider_show_id TEXT,
            show_title TEXT NOT NULL,
            show_year INTEGER,
            season_number INTEGER NOT NULL,
            episode_number INTEGER NOT NULL,
            episode_title TEXT NOT NULL,
            quality TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('hardlink', 'copy', 'test')),
            conflict_policy TEXT NOT NULL CHECK (conflict_policy IN ('skip', 'replace', 'index', 'fail')),
            result TEXT NOT NULL,
            error TEXT,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE library_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_type TEXT NOT NULL CHECK (media_type IN ('tv', 'anime')),
            output_path TEXT NOT NULL UNIQUE,
            size INTEGER,
            mtime REAL,
            present INTEGER NOT NULL DEFAULT 1,
            import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
            discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.close()

    database = Database(db_path)
    database.init()

    database.insert_import(
        {
            "source_path": str(tmp_path / "source.mkv"),
            "source_size": None,
            "source_mtime": None,
            "source_device": None,
            "source_inode": None,
            "output_path": str(tmp_path / "films" / "Film.mkv"),
            "media_type": "film",
            "provider": None,
            "provider_show_id": None,
            "show_title": "Film",
            "show_year": 2026,
            "season_number": 0,
            "episode_number": 0,
            "episode_title": "Film",
            "quality": "1080p",
            "action": "copy",
            "conflict_policy": "skip",
            "result": "imported",
            "error": None,
        }
    )

    assert database.list_imports()[0]["media_type"] == "film"


def test_latest_imports_for_sources_returns_newest_status(tmp_path: Path) -> None:
    database = Database(tmp_path / "tvsorter.db")
    database.init()
    source = (tmp_path / "source.mkv").resolve()

    base_record = {
        "source_path": str(source),
        "source_size": None,
        "source_mtime": None,
        "source_device": None,
        "source_inode": None,
        "output_path": str(tmp_path / "library" / "Film.mkv"),
        "media_type": "film",
        "provider": None,
        "provider_show_id": None,
        "show_title": "Film",
        "show_year": 2026,
        "season_number": 0,
        "episode_number": 0,
        "episode_title": "Film",
        "quality": "1080p",
        "action": "copy",
        "conflict_policy": "skip",
        "result": "failed",
        "error": "Permission denied",
    }
    database.insert_import(base_record)
    database.insert_import(base_record | {"result": "imported", "error": None})

    rows = database.latest_imports_for_sources([source])

    assert rows[str(source)]["result"] == "imported"


def test_source_status_overrides_can_be_set_and_cleared(tmp_path: Path) -> None:
    database = Database(tmp_path / "tvsorter.db")
    database.init()
    source = tmp_path / "source.mkv"
    second_source = tmp_path / "second.mkv"

    database.set_source_status_overrides([source, second_source], "none")
    rows = database.source_status_overrides([source, second_source])

    assert rows[str(source.resolve())]["status"] == "none"
    assert rows[str(second_source.resolve())]["status"] == "none"

    database.set_source_status_overrides([source, second_source], None)

    assert database.source_status_overrides([source, second_source]) == {}
