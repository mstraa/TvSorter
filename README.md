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

## Proxmox LXC

Run this from the Proxmox VE host to create a privileged Debian LXC and install TvSorter from GitHub:

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/mstraa/TvSorter/main/scripts/create-proxmox-lxc.sh)" -- \
  --ctid 120 \
  --mount /tank/downloads:/mnt/downloads \
  --mount /tank/media/TV:/mnt/media/TV \
  --mount /tank/media/Anime:/mnt/media/Anime
```

The script prompts for root disk and template storage when run interactively. Use `--help` to see static IP, SSH key, storage, and sizing options.

If your Proxmox node does not have `local-lvm`, use the prompt, pass `--storage auto`, or inspect choices with `pvesm status`.
