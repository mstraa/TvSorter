from tvsorter.parser import parse_media_filename


def test_parse_sxxeyy_filename() -> None:
    parsed = parse_media_filename("Fringe.2008.S01E02.The.Same.Old.Story.1080p.WEB-DL.mkv")

    assert parsed.title == "Fringe"
    assert parsed.year == 2008
    assert parsed.season == 1
    assert parsed.episode == 2
    assert parsed.episode_title == "The Same Old Story"
    assert parsed.quality == "1080p"


def test_parse_one_x_two_filename() -> None:
    parsed = parse_media_filename("Cowboy Bebop - 1x03 - Honky Tonk Women [720p].mkv")

    assert parsed.title == "Cowboy Bebop"
    assert parsed.season == 1
    assert parsed.episode == 3
    assert parsed.episode_title == "Honky Tonk Women"
    assert parsed.quality == "720p"
