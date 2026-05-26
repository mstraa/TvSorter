from tvsorter.parser import parse_film_filename, parse_media_filename


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


def test_parse_anime_style_episode_filename() -> None:
    parsed = parse_media_filename("Claymore.E02.MULTi.1080p.BluRay.x264-Kazuto.mkv")

    assert parsed.title == "Claymore"
    assert parsed.season == 1
    assert parsed.episode == 2
    assert parsed.episode_title == "Episode"
    assert parsed.quality == "1080p"


def test_parse_film_filename() -> None:
    parsed = parse_film_filename("Blade.Runner.2049.2017.2160p.BluRay.x265.mkv")

    assert parsed.title == "Blade Runner 2049"
    assert parsed.year == 2017
    assert parsed.season == 0
    assert parsed.episode == 0
    assert parsed.episode_title == "Film"
    assert parsed.quality == "2160p"


def test_parse_film_filename_strips_release_language_tags() -> None:
    parsed = parse_film_filename("12.Angry.Men.1957.MULTI.VFF.720p.HDRip.x264.AC3.2.0.mkv.mkv")

    assert parsed.title == "12 Angry Men"
    assert parsed.year == 1957
    assert parsed.quality == "720p"
