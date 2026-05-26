# TvSorter

TvSorter is a LAN-only web app for curating mounted TV/anime files into clean output libraries by hardlinking or copying selected episodes.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
TVSORTER_DATA_DIR=.local-data .venv/bin/uvicorn tvsorter.main:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`, configure input/output folders, then browse and import.

## Verification

```sh
.venv/bin/python -m pytest
```

## Configuration

Environment variables:

- `TVSORTER_DATA_DIR`: directory for SQLite data, default `~/.local/share/tvsorter`
- `TVSORTER_DATABASE`: explicit SQLite database path
- `TVSORTER_HOST`: service host, default `0.0.0.0`
- `TVSORTER_PORT`: service port, default `8080`

See [docs/PRD.md](docs/PRD.md) and [DEV.md](DEV.md) before development work.

