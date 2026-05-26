from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    database_path: Path
    host: str
    port: int


def load_config() -> AppConfig:
    data_dir = Path(
        os.environ.get("TVSORTER_DATA_DIR", Path.home() / ".local" / "share" / "tvsorter")
    ).expanduser()
    database_path = Path(os.environ.get("TVSORTER_DATABASE", data_dir / "tvsorter.db")).expanduser()
    host = os.environ.get("TVSORTER_HOST", "0.0.0.0")
    port = int(os.environ.get("TVSORTER_PORT", "8080"))
    return AppConfig(data_dir=data_dir, database_path=database_path, host=host, port=port)

