from pathlib import Path

import pytest

from tvsorter.filesystem import expand_video_files, resolve_under_root


def test_resolve_under_root_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(ValueError):
        resolve_under_root(root, "../outside")


def test_expand_video_files_ignores_subtitles(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "episode.mkv").write_text("video")
    (root / "episode.srt").write_text("subtitle")

    files = expand_video_files(root, [""])

    assert files == [(root / "episode.mkv").resolve()]

