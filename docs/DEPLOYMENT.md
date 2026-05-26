# LXC Deployment

This is the initial deployment shape for running TvSorter inside a privileged LXC container.

## Automated Proxmox Creation

From the Proxmox VE host, run:

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/mstraa/TvSorter/main/scripts/create-proxmox-lxc.sh)" -- \
  --ctid 120 \
  --mount /tank/downloads:/mnt/downloads \
  --mount /tank/media/TV:/mnt/media/TV \
  --mount /tank/media/Anime:/mnt/media/Anime
```

The script:

- Creates a privileged Debian LXC.
- Downloads a Debian standard template through `pveam` when needed.
- Adds any requested bind mounts.
- Installs Python, ffmpeg, Git, and TvSorter from GitHub.
- Configures the Proxmox LXC console to autologin as root.
- Creates and starts the `tvsorter.service` systemd unit.

Use `scripts/create-proxmox-lxc.sh --help` for all options.

When run interactively, the script prompts for root disk and template storage. `--storage auto` chooses the first Proxmox storage that advertises container root disk support. To choose manually, run `pvesm status` on the Proxmox host and pass the wanted storage name with `--storage`.

Console autologin is configured with systemd overrides for `container-getty@1.service` and `getty@tty1.service`, matching the usual Proxmox helper-script behavior.

## Updating In The LXC

The Proxmox creation script installs `/usr/local/bin/update`, which updates `/opt/tvsorter` to the latest GitHub `main`, refreshes the Python virtual environment, and restarts `tvsorter.service`.
It also reapplies the console autologin systemd overrides.

Inside the LXC:

```sh
update
```

For an existing container created before this command existed:

```sh
curl -fsSL https://raw.githubusercontent.com/mstraa/TvSorter/main/scripts/update-tvsorter.sh -o /usr/local/bin/update-tvsorter
chmod 0755 /usr/local/bin/update-tvsorter
ln -sf /usr/local/bin/update-tvsorter /usr/local/bin/update
```

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
