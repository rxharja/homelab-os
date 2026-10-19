# Architecture

## Layers

| Layer | Where | Mutable? | Source of truth |
|---|---|---|---|
| OS + packages + Quadlets + templates | `/usr` | No (image) | this repo |
| Machine config + secrets | `/etc/homelab` | Yes | you (back it up) |
| Rendered config | `/var/lib/homelab/config` | regenerated every boot | templates + `/etc/homelab` |
| App state | `/var/lib/homelab/appdata` | Yes | restic |
| Media | `/var/mnt/media/{riven,zurg}` | FUSE, virtual | Real-Debrid |

Nothing secret is in the image or git. `homelab-render.service` runs before every
container and re-creates rendered config, Podman secrets, Cockpit origins, firewall
rules and the Tailscale login. Edit `/etc/homelab/*`, run
`sudo systemctl restart homelab-render <app>`, and the change is applied.

## Request → playback flow

1. Neptune or a browser → **Seerr** request (auto-approved).
2. **Riven** polls Seerr (60 s), scrapes **Torrentio / Comet**, ranks results with
   `ranking.json` (remux > 4K DV/HDR10+ > TrueHD/Atmos), adds the pick to **Real-Debrid**
   through **StremThru**.
3. RivenVFS (FUSE inside the Riven container) exposes it at `/mount`, which propagates through
   an `rshared` bind to `/var/mnt/media/riven` on the host.
4. **Jellyfin** sees `/var/mnt/media` at `/media` via `rslave`, so new and remounted FUSE trees
   appear without a restart. Riven tells Jellyfin to refresh `/media/riven`.
5. Neptune/Infuse direct-plays from Jellyfin. Bytes stream from Real-Debrid on demand.

Zurg + rclone does the same for everything in your RD account (DMM hand-picks) at
`/var/mnt/media/zurg`.

## Why rootful here

* FUSE propagation from a container to the host and into another container needs real
  mount namespaces: `SYS_ADMIN`, `/dev/fuse`, `rshared`/`rslave`. That runs cleanly rootful.
* Ports 53/80/443 bind directly, with no firewall redirects.
* Isolation is kept with `UserNS=auto` (each container gets its own unprivileged UID range)
  for everything except Riven (FUSE), Jellyfin (reads the root-owned FUSE mounts) and Ollama
  (GPU devices).

## Networking and exposure

* Only DNS (53), HTTP/S (80/443), Jellyfin (8096), Ollama (11434) and the AdGuard UI (3001) are LAN-published.
  Seerr, Open WebUI and AdGuard's UI go through Caddy. Postgres, Redis, Zurg and Riven's API
  stay on the internal network or localhost.
* **Ollama has no auth.** It is LAN-only by design. Never port-forward it.
* No router port forwards at all. Remote access goes through Tailscale; DNS-01 certs don't need inbound ports.
* Rootful Podman's published ports are handled by netavark's own nftables rules, so firewalld
  zones don't filter them. The router's lack of port forwards is the real perimeter.

## Updates

* **Apps**: `AutoUpdate=registry` + `podman-auto-update.timer` (daily). Podman rolls back a container that fails to start.
* **OS**: CI rebuilds weekly. `bootc-fetch-apply-updates.timer` pulls Sunday 04:30 and reboots
  into the new image. Bound images (`/usr/lib/bootc/bound-images.d`) are pulled *before* the
  reboot, so containers are never missing. `sudo bootc rollback && sudo reboot` undoes a bad update.

## GPU (Radeon 680M, gfx1035)

* Jellyfin: VAAPI via `/dev/dri` (enable in Dashboard → Playback; mostly direct play anyway).
* Ollama: ROCm image with `HSA_OVERRIDE_GFX_VERSION=10.3.0`. **Verify on hardware**
  (`podman logs ollama | grep -i gpu`). If ROCm won't take the iGPU, use the Vulkan fallback in operations.md.
  Raise the UMA frame buffer in BIOS (e.g. 8 GB) so more of the 24 GB is GPU-addressable.
