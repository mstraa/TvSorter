from tvsorter.formatting import human_file_size


def test_human_file_size_formats_french_units() -> None:
    assert human_file_size(None) == ""
    assert human_file_size(512) == "512 o"
    assert human_file_size(22 * 1024 * 1024) == "22 Mo"
    assert human_file_size(int(1.34 * 1024 * 1024 * 1024)) == "1,34 Go"
