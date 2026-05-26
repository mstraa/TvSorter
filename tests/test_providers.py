from typing import Any

import pytest

import tvsorter.providers as providers_module
from tvsorter.db import Database
from tvsorter.providers import MetadataProviders


@pytest.mark.anyio
async def test_wikidata_film_search_returns_film_candidates(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "tvsorter.db")
    database.init()

    async def fake_get_json(url: str) -> Any:
        if "wbsearchentities" in url:
            return {"search": [{"id": "Q2345", "label": "12 Angry Men"}]}
        return {
            "entities": {
                "Q2345": {
                    "labels": {"en": {"value": "12 Angry Men"}},
                    "descriptions": {"en": {"value": "1957 American courtroom drama film"}},
                    "claims": {
                        "P31": [
                            {
                                "mainsnak": {
                                    "datavalue": {"value": {"id": "Q11424"}}
                                }
                            }
                        ],
                        "P577": [
                            {
                                "mainsnak": {
                                    "datavalue": {"value": {"time": "+1957-04-10T00:00:00Z"}}
                                }
                            }
                        ],
                    },
                }
            }
        }

    monkeypatch.setattr(providers_module, "_get_json", fake_get_json)

    candidates = await MetadataProviders(database).search_wikidata_films("12 Angry Men")

    assert candidates[0].provider == "wikidata"
    assert candidates[0].provider_id == "Q2345"
    assert candidates[0].title == "12 Angry Men"
    assert candidates[0].year == 1957


@pytest.mark.anyio
async def test_film_search_uses_imdb_suggestions_first(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "tvsorter.db")
    database.init()

    async def fake_get_json(url: str) -> Any:
        assert "sg.media-imdb.com" in url
        return {
            "d": [
                {
                    "id": "tt0050083",
                    "l": "12 Angry Men",
                    "qid": "movie",
                    "q": "feature",
                    "s": "Henry Fonda, Lee J. Cobb",
                    "y": 1957,
                },
                {
                    "id": "nm0000000",
                    "l": "Not a film result",
                    "qid": "name",
                },
            ]
        }

    monkeypatch.setattr(providers_module, "_get_json", fake_get_json)

    candidates = await MetadataProviders(database).search("film", "12 Angry Men")

    assert candidates == [
        providers_module.ShowCandidate(
            provider="imdb",
            provider_id="tt0050083",
            title="12 Angry Men",
            year=1957,
            summary="feature - Henry Fonda, Lee J. Cobb",
        )
    ]
