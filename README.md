# homelab-os

This repo defines the entire whole home server as **one bootable container image** (Fedora bootc).
Build it in CI, install it once, and the box configures itself on every boot from
two small files in `/etc/homelab/`. OS + containers update together, and
`bootc rollback` undoes a bad update.

```
git push ──► GitHub Actions ──► ghcr.io/<you>/homelab-os:latest
                                         │  bootc upgrade (weekly, auto)
                                         ▼
                    Server Hardware / VM  ── /etc/homelab/*.env (yours, never in git)
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
| Cockpit | Web admin for host and containers | `https://LAN_IP:9090` (self-signed) |
| Tailscale | Remote access, no port forwarding | tailnet |
| restic | Nightly backups 03:30 | n/a |

## Layout

`rootfs/` is laid out exactly like the target filesystem and copied in with a single
`COPY rootfs/ /`, so the path in the repo is the path on the box.

```
Containerfile                              packages, then COPY rootfs/ /
rootfs/
  usr/share/containers/systemd/            rootful Quadlets (one per container)
  usr/lib/systemd/system/                  host units: media mount, render, rclone,
                                           backup, and the bootc update schedule
  usr/lib/tmpfiles.d/homelab.conf          every directory the containers mount
  usr/lib/sysctl.d/99-tailscale.conf       ip_forward, for the subnet router
  usr/lib/systemd/resolved.conf.d/         frees port 53 for AdGuard
  usr/bin/homelab-*                        render, backup, restore, import, status
  usr/share/homelab/Caddyfile              static proxy config ({$DOMAIN} at runtime)
  usr/share/homelab/templates/             the only two rendered files: riven.env
                                           and zurg's config.yml (both hold a secret)
  usr/share/homelab/rclone.conf            the Zurg WebDAV remote
  usr/share/homelab/examples/              homelab.env, secrets.env, riven.extra.env
  etc/homelab/ranking.json                 Riven quality ranking; a default in /etc, so
                                           bootc's 3-way merge keeps your edits
scripts/export-devbox.sh                   runs on the old dev box, not in the image
bootc/                                     bootc-image-builder configs (ISO and VM)
images/caddy/                              Caddy + Cloudflare DNS plugin
docs/                                      architecture, first boot, migration, operations
```

## Quick start

1. Push this repo to GitHub. CI publishes `ghcr.io/<you>/homelab-os` and `caddy-cloudflare`.
   Make both packages **public** (or add a pull secret on the box).
2. Put your SSH key in `bootc/config.toml`, then `make iso OWNER=<you>`, `dd` it to a USB stick, and boot the mini PC from it.
3. On the box:
   ```bash
   sudo cp /usr/share/homelab/examples/{homelab,secrets}.env /etc/homelab/
   sudo chmod 600 /etc/homelab/secrets.env && sudoedit /etc/homelab/*.env
   sudo systemctl restart homelab-render && sudo systemctl start adguard caddy jellyfin seerr riven ollama open-webui
   ```
4. Follow [docs/first-boot.md](docs/first-boot.md), or [docs/migration.md](docs/migration.md) to carry over the dev box state.

Day-2: [docs/operations.md](docs/operations.md).
