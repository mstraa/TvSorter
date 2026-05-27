from pathlib import Path

from tvsorter.importer import ImportRequest
from tvsorter.main import ImportJob


def _request(source: Path, output_root: Path) -> ImportRequest:
    return ImportRequest(
        source_path=source,
        output_root=output_root,
        media_type="tv",
        show_title="Caprica",
        show_year=2010,
        season_number=1,
        episode_number=1,
        episode_title="Pilot",
        quality="1080p",
        action="copy",
        conflict_policy="skip",
    )


def test_import_job_snapshot_includes_detailed_progress(tmp_path: Path) -> None:
    source = tmp_path / "Caprica.S01E01.1080p.mkv"
    source.write_bytes(b"episode")
    requests = [_request(source, tmp_path / "tv"), _request(source, tmp_path / "tv")]
    job = ImportJob(id="job", requests=requests, total_units=200)

    with job.lock:
        job.completed_units = 50
        job.completed_items = 0
        job.current_item_index = 1
        job.current_item = source.name
        job.current_action = "copy"
        job.current_item_bytes = 25
        job.current_item_total = 100

    snapshot = job.snapshot()

    assert snapshot["percent"] == 25
    assert snapshot["current_item"] == source.name
    assert snapshot["current_item_percent"] == 25
    assert snapshot["current_item_bytes"] == 25
    assert snapshot["current_item_total"] == 100
    assert snapshot["completed_items"] == 0
    assert snapshot["total_items"] == 2
