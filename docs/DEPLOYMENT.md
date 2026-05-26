# LXC Deployment

This is the initial deployment shape for running TvSorter inside a privileged LXC container.

## Package Install

```sh
apt update
apt install -y python3 python3-venv ffmpeg
useradd --system --home /var/lib/tvsorter --create-home --shell /usr/sbin/nologin tvsorter
```

Clone or copy the project to `/opt/tvsorter`, then install dependencies:

```sh
cd /opt/tvsorter
python3 -m venv .venv
.venv/bin/python -m pip install -e .
install -d -o tvsorter -g tvsorter /var/lib/tvsorter
```

## Mounts

Mount input and output folders into the LXC before starting the service.

Example paths:

```text
/mnt/downloads
/mnt/media/TV
/mnt/media/Anime
```

The service user needs read access to input roots and write access to TV/Anime output roots.

Hardlinks require source and output to be on the same filesystem. If they are mounted from different devices or datasets, use copy.

## systemd Unit

Create `/etc/systemd/system/tvsorter.service`:

```ini
[Unit]
Description=TvSorter
After=network-online.target
Wants=network-online.target

[Service]
User=tvsorter
Group=tvsorter
WorkingDirectory=/opt/tvsorter
Environment=TVSORTER_DATA_DIR=/var/lib/tvsorter
Environment=TVSORTER_HOST=0.0.0.0
Environment=TVSORTER_PORT=8080
ExecStart=/opt/tvsorter/.venv/bin/uvicorn tvsorter.main:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable it:

```sh
systemctl daemon-reload
systemctl enable --now tvsorter
```

