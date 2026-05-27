from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS input_roots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    source_size INTEGER,
    source_mtime REAL,
    source_device INTEGER,
    source_inode INTEGER,
    output_path TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('tv', 'anime', 'film')),
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

CREATE TABLE IF NOT EXISTS library_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_type TEXT NOT NULL CHECK (media_type IN ('tv', 'anime', 'film')),
    output_path TEXT NOT NULL UNIQUE,
    size INTEGER,
    mtime REAL,
    present INTEGER NOT NULL DEFAULT 1,
    import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS provider_cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_status_overrides (
    source_path TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('none', 'imported', 'failed', 'skipped', 'preview', 'conflict')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate_media_type_checks(conn)

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_json_setting(self, key: str, default: Any) -> Any:
        value = self.get_setting(key)
        return json.loads(value) if value else default

    def set_json_setting(self, key: str, value: Any) -> None:
        self.set_setting(key, json.dumps(value))

    def replace_input_roots(self, paths: list[str]) -> None:
        unique_paths = []
        for path in paths:
            if path and path not in unique_paths:
                unique_paths.append(path)
        with self.connect() as conn:
            conn.execute("DELETE FROM input_roots")
            conn.executemany("INSERT INTO input_roots (path) VALUES (?)", [(path,) for path in unique_paths])

    def list_input_roots(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id, path FROM input_roots ORDER BY path").fetchall()
        return list(rows)

    def get_input_root(self, root_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT id, path FROM input_roots WHERE id = ?", (root_id,)).fetchone()

    def insert_import(self, record: dict[str, Any]) -> int:
        columns = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        with self.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO imports ({columns}) VALUES ({placeholders})",
                tuple(record.values()),
            )
            import_id = int(cursor.lastrowid)
            if record["result"] in {"imported", "preview", "skipped"}:
                self._upsert_library_file(conn, record, import_id)
        return import_id

    def _upsert_library_file(
        self, conn: sqlite3.Connection, record: dict[str, Any], import_id: int | None = None
    ) -> None:
        output_path = Path(record["output_path"])
        size = None
        mtime = None
        present = 0
        if output_path.exists():
            stat = output_path.stat()
            size = stat.st_size
            mtime = stat.st_mtime
            present = 1
        conn.execute(
            """
            INSERT INTO library_files (media_type, output_path, size, mtime, present, import_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(output_path) DO UPDATE SET
                media_type = excluded.media_type,
                size = excluded.size,
                mtime = excluded.mtime,
                present = excluded.present,
                import_id = COALESCE(excluded.import_id, library_files.import_id),
                updated_at = CURRENT_TIMESTAMP
            """,
            (record["media_type"], record["output_path"], size, mtime, present, import_id),
        )

    def list_imports(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM imports ORDER BY imported_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return list(rows)

    def latest_imports_for_sources(self, source_paths: list[Path]) -> dict[str, sqlite3.Row]:
        if not source_paths:
            return {}
        normalized_paths = [str(path.resolve()) for path in source_paths]
        placeholders = ", ".join(["?"] * len(normalized_paths))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM imports
                WHERE id IN (
                    SELECT MAX(id)
                    FROM imports
                    WHERE source_path IN ({placeholders})
                    GROUP BY source_path
                )
                """,
                normalized_paths,
            ).fetchall()
        return {row["source_path"]: row for row in rows}

    def source_status_overrides(self, source_paths: list[Path]) -> dict[str, sqlite3.Row]:
        if not source_paths:
            return {}
        normalized_paths = [str(path.resolve()) for path in source_paths]
        placeholders = ", ".join(["?"] * len(normalized_paths))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM source_status_overrides
                WHERE source_path IN ({placeholders})
                """,
                normalized_paths,
            ).fetchall()
        return {row["source_path"]: row for row in rows}

    def set_source_status_override(self, source_path: Path, status: str | None) -> None:
        self.set_source_status_overrides([source_path], status)

    def set_source_status_overrides(self, source_paths: list[Path], status: str | None) -> None:
        normalized_paths = [str(path.resolve()) for path in source_paths]
        if not normalized_paths:
            return
        with self.connect() as conn:
            if status is None:
                conn.executemany(
                    "DELETE FROM source_status_overrides WHERE source_path = ?",
                    [(path,) for path in normalized_paths],
                )
                return
            conn.executemany(
                """
                INSERT INTO source_status_overrides (source_path, status)
                VALUES (?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [(path, status) for path in normalized_paths],
            )

    def list_library_files(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM library_files ORDER BY media_type, output_path"
            ).fetchall()
        return list(rows)

    def upsert_discovered_file(self, media_type: str, path: Path) -> None:
        stat = path.stat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO library_files (media_type, output_path, size, mtime, present)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(output_path) DO UPDATE SET
                    size = excluded.size,
                    mtime = excluded.mtime,
                    present = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (media_type, str(path), stat.st_size, stat.st_mtime),
            )

    def mark_missing_outside(self, roots: dict[str, Path]) -> None:
        rows = self.list_library_files()
        with self.connect() as conn:
            for row in rows:
                path = Path(row["output_path"])
                root = roots.get(row["media_type"])
                if root and _is_relative_to(path, root) and not path.exists():
                    conn.execute(
                        "UPDATE library_files SET present = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (row["id"],),
                    )

    def get_cache(self, key: str) -> Any | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM provider_cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_cache(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_cache (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, created_at = CURRENT_TIMESTAMP
                """,
                (key, json.dumps(value)),
            )

    def _migrate_media_type_checks(self, conn: sqlite3.Connection) -> None:
        for table in ("imports", "library_files"):
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if row and "media_type IN ('tv', 'anime')" in row["sql"]:
                self._recreate_media_table(conn, table)

    def _recreate_media_table(self, conn: sqlite3.Connection, table: str) -> None:
        temp_table = f"{table}_migration"
        conn.execute(f"ALTER TABLE {table} RENAME TO {temp_table}")
        conn.executescript(_table_schema(table))
        old_columns = [
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({temp_table})").fetchall()
        ]
        new_columns = [
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            if row["name"] in old_columns
        ]
        column_sql = ", ".join(new_columns)
        conn.execute(
            f"INSERT INTO {table} ({column_sql}) SELECT {column_sql} FROM {temp_table}"
        )
        conn.execute(f"DROP TABLE {temp_table}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _table_schema(table: str) -> str:
    statements = {
        "imports": """
CREATE TABLE imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    source_size INTEGER,
    source_mtime REAL,
    source_device INTEGER,
    source_inode INTEGER,
    output_path TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('tv', 'anime', 'film')),
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
""",
        "library_files": """
CREATE TABLE library_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_type TEXT NOT NULL CHECK (media_type IN ('tv', 'anime', 'film')),
    output_path TEXT NOT NULL UNIQUE,
    size INTEGER,
    mtime REAL,
    present INTEGER NOT NULL DEFAULT 1,
    import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
""",
    }
    return statements[table]
