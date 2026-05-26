from pathlib import Path

from tvsorter.importer import ImportRequest, execute_import


def _request(source: Path, output_root: Path, action: str, conflict_policy: str = "skip") -> ImportRequest:
    return ImportRequest(
        source_path=source,
        output_root=output_root,
        media_type="tv",
        show_title="Fringe",
        show_year=2008,
        season_number=1,
        episode_number=1,
        episode_title="Pilot",
        quality="1080p",
        action=action,
        conflict_policy=conflict_policy,
    )


def test_copy_import_leaves_source_untouched(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    source.write_text("episode")
    output_root = tmp_path / "library"

    result = execute_import(_request(source, output_root, "copy"))

    assert result.result == "imported"
    assert source.exists()
    assert result.final_path.read_text() == "episode"


def test_skip_conflict_does_not_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    source.write_text("new")
    output_root = tmp_path / "library"
    first = execute_import(_request(source, output_root, "copy"))
    first.final_path.write_text("existing")

    result = execute_import(_request(source, output_root, "copy", "skip"))

    assert result.result == "skipped"
    assert first.final_path.read_text() == "existing"


def test_index_conflict_keeps_both(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    source.write_text("episode")
    output_root = tmp_path / "library"
    first = execute_import(_request(source, output_root, "copy"))

    result = execute_import(_request(source, output_root, "copy", "index"))

    assert result.result == "imported"
    assert first.final_path.exists()
    assert result.final_path.name.endswith("(2).mkv")


def test_film_import_uses_film_naming(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    source.write_text("film")
    output_root = tmp_path / "films"
    request = ImportRequest(
        source_path=source,
        output_root=output_root,
        media_type="film",
        show_title="Blade Runner 2049",
        show_year=2017,
        season_number=0,
        episode_number=0,
        episode_title="Film",
        quality="2160p",
        action="copy",
        conflict_policy="skip",
    )

    result = execute_import(request)

    assert result.result == "imported"
    assert result.final_path == output_root / "Blade Runner 2049 (2017)" / "Blade Runner 2049 (2017) - 2160p.mkv"
