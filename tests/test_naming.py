from pathlib import Path

from tvsorter.naming import destination_path, sanitize_component


def test_sanitize_component_removes_invalid_path_chars() -> None:
    assert sanitize_component('A/B:C*D?"E') == "A B C D E"


def test_destination_path_uses_expected_tree() -> None:
    result = destination_path(
        output_root=Path("/media/TV"),
        title="Fringe",
        year=2008,
        season=1,
        episode=1,
        episode_title="Pilot",
        quality="1080p",
        source_path=Path("source.mkv"),
    )

    assert result == Path("/media/TV/Fringe (2008)/Season 01/Fringe (2008) - S01E01 - Pilot - 1080p.mkv")

