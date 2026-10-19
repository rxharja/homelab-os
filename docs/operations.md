# Operations

| Task | Command |
|---|---|
| Health | `sudo homelab-status` |
| Logs | `journalctl -u riven -f`, `podman logs -f jellyfin` |
| Riven log, noise filtered | `journalctl -u riven -f \| grep -E ' - [a-z-]+ - (info\|warn\|error):' \| grep -v ' - vfs - '` |
| Change config | `sudoedit /etc/homelab/homelab.env && sudo systemctl restart homelab-render <app>` |
| Change ranking now | `sudo cp my.json /etc/homelab/ranking.json && sudo systemctl restart homelab-render riven` (or commit to `files/riven/ranking.json`) |
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

Swap `quadlets/ollama.container` for a llama.cpp Vulkan server
(`ghcr.io/ggml-org/llama.cpp:server-vulkan`, `AddDevice=/dev/dri`, a GGUF file in
`/var/lib/homelab/appdata/llama`, `--port 11434`). It exposes an OpenAI-compatible API;
point Open WebUI at it as an "OpenAI" connection. Check whether Neptune accepts an
OpenAI-style endpoint before switching.

## Adding a service later (Mealie, Home Assistant, ...)

1. Add `quadlets/<app>.container` (copy `seerr.container`: `UserNS=auto`, a `:Z,U` volume under `/var/lib/homelab/appdata/<app>`).
2. Add a `@<app>` block to `templates/Caddyfile`. Skip this for Home Assistant/Music Assistant
   if they need host networking and mDNS; give those `Network=host`.
3. Add the data dir to `homelab-backup` if it uses SQLite and needs stopping.
4. Push. The next `bootc upgrade` ships it.
