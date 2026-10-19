# homelab-os

The whole home server as **one bootable container image** (Fedora bootc).
Build it in CI, install it once, and the box configures itself on every boot from
two small files in `/etc/homelab/`. OS + containers update together, and
`bootc rollback` undoes a bad update.

```
git push ──► GitHub Actions ──► ghcr.io/<you>/homelab-os:latest
                                         │  bootc upgrade (weekly, auto)
                                         ▼
                    Beelink SER5 MAX  ── /etc/homelab/*.env (yours, never in git)
                                       └ /var/lib/homelab   (state, backed up by restic)
```

## What's inside

| Service | Role | Reach it at |
|---|---|---|
| AdGuard Home | LAN DNS, ad blocking, `*.DOMAIN` rewrite | `adguard.DOMAIN`, DNS on :53 |
| Caddy | TLS reverse proxy, wildcard cert via Cloudflare DNS-01 | :80/:443 |
| Jellyfin | Media server (680M VAAPI) | `jellyfin.DOMAIN`, `LAN_IP:8096` |
| Seerr | Requests and discovery | `seerr.DOMAIN` |
| Riven + Postgres + Redis | Requests → scrape → Real-Debrid → FUSE library | internal |
| Zurg + rclone | Whole RD library (DMM hand-picks) at `/var/mnt/media/zurg` | internal |
| Ollama (ROCm) | Local LLM on the 680M | `LAN_IP:11434` (Neptune) |
| Open WebUI | Chat front end | `chat.DOMAIN` |
| Cockpit | Web admin for host and containers | `cockpit.DOMAIN` |
| Tailscale | Remote access, no port forwarding | tailnet |
| restic | Nightly backups 03:30 | n/a |

## Layout

```
Containerfile            the OS image
quadlets/                rootful Quadlets -> /usr/share/containers/systemd
templates/               rendered at boot with values from /etc/homelab
files/riven/ranking.json Riven quality ranking (config as code)
systemd/                 host units: shared media mount, render, rclone, backup, update schedule
scripts/                 homelab-render/backup/restore/import/status, export-devbox.sh
examples/                homelab.env, secrets.env, riven.extra.env
bootc/                   bootc-image-builder configs (ISO and VM)
images/caddy/            Caddy + Cloudflare DNS plugin
docs/                    architecture, first boot, migration, operations
```

## Quick start

1. Push this repo to GitHub. CI publishes `ghcr.io/<you>/homelab-os` and `caddy-cloudflare`.
   Make both packages **public** (or add a pull secret on the box).
2. Put your SSH key in `bootc/config.toml`, then `make iso OWNER=<you>`, `dd` it to a USB stick, and boot the mini PC from it.
3. On the box:
   ```bash
   sudo cp /usr/share/homelab/examples/{homelab,secrets}.env /etc/homelab/
   sudo chmod 600 /etc/homelab/secrets.env && sudoedit /etc/homelab/*.env
   sudo systemctl restart homelab-render && sudo systemctl start adguard caddy jellyfin seerr riven ollama open-webui zurg-mount
   ```
4. Follow [docs/first-boot.md](docs/first-boot.md), or [docs/migration.md](docs/migration.md) to carry over the dev box state.

Day-2: [docs/operations.md](docs/operations.md).
