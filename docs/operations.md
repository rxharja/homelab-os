# Operations

| Task | Command |
|---|---|
| Health | `sudo homelab-status` |
| Logs | `journalctl -u riven -f`, `podman logs -f jellyfin` |
| Riven log, noise filtered | `journalctl -u riven -f \| grep -E ' - [a-z-]+ - (info\|warn\|error):' \| grep -v ' - vfs - '` |
| Admin UI | `https://LAN_IP:9090` (Cockpit; self-signed cert, so accept the warning) |
| Change config | `sudoedit /etc/homelab/homelab.env && sudo systemctl restart homelab-render <app>` |
| Change ranking now | `sudoedit /etc/homelab/ranking.json && sudo systemctl restart riven` (Riven mounts it straight from `/etc`) |
| Change the shipped ranking default | commit to `rootfs/etc/homelab/ranking.json`; bootc's 3-way `/etc` merge leaves a locally edited file alone |
| Update OS now | `sudo bootc upgrade --apply` |
| Undo OS update | `sudo bootc rollback && sudo reboot` |
| Update apps now | `sudo podman auto-update` |
| Backup now | `sudo systemctl start homelab-backup` |
| Restore everything | `sudo homelab-restore [snapshot]` |
| Riven TUI | `ssh -L 3000:127.0.0.1:3000 redon@homelab`, then point the TUI at localhost:3000 |
| Try an image change in a VM | `make qcow2 OWNER=<you>`, boot `output/qcow2/disk.qcow2` in GNOME Boxes |

## Disaster recovery

New disk or new box: install the ISO, restore `/etc/homelab` from your password manager or
restic, then `sudo homelab-restore`. Media needs no backup; it lives on Real-Debrid.

## Ollama Vulkan fallback (if ROCm won't use the 680M)

Swap `rootfs/usr/share/containers/systemd/ollama.container` for a llama.cpp Vulkan server
(`ghcr.io/ggml-org/llama.cpp:server-vulkan`, `AddDevice=/dev/dri`, a GGUF file in
`/var/lib/homelab/appdata/llama`, `--port 11434`). It exposes an OpenAI-compatible API;
point Open WebUI at it as an "OpenAI" connection. Check whether Neptune accepts an
OpenAI-style endpoint before switching.

## Adding a service later (Mealie, Home Assistant, ...)

1. Add `rootfs/usr/share/containers/systemd/<app>.container` (copy `seerr.container`:
   `UserNS=auto`, `Requires=`/`After=homelab-render.service`, a `:Z,U` volume under
   `/var/lib/homelab/appdata/<app>`).
2. Add its data dir to `rootfs/usr/lib/tmpfiles.d/homelab.conf`, so it exists on first boot.
3. Add a `@<app>` block to `rootfs/usr/share/homelab/Caddyfile`, using `{$DOMAIN}`. Skip this
   for Home Assistant/Music Assistant if they need host networking and mDNS; give those
   `Network=host`.
4. Add the data dir to `homelab-backup` if it uses SQLite and needs stopping.
5. Push. The next `bootc upgrade` ships it.
