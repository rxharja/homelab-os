# Migrating from the Pop!_OS dev box

Your current state (Jellyfin users and watch history, Seerr requests, the Riven DB, AdGuard
rules, the Caddy cert, Open WebUI chats) moves over in one tarball.

## 1. On the Pop box

```bash
cd ~/homelab && ./scripts/export-devbox.sh          # -> ~/homelab-export.tar.zst
scp ~/homelab-export.tar.zst homelab@LAN_IP:
```

## 2. On the mini PC (after README quick start step 3)

```bash
sudo homelab-import ~/homelab-export.tar.zst
sudo grep COMET /etc/homelab/riven.env.devbox | sudo tee /etc/homelab/riven.extra.env
sudo chmod 600 /etc/homelab/riven.extra.env
sudo systemctl restart homelab-render riven
sudo homelab-status
rm ~/homelab-export.tar.zst          # it contains secrets
```

The import rewrites AdGuard's `*.DOMAIN` answer from the dev box IP to the new `LAN_IP`.
Jellyfin library paths are unchanged (`/media/riven/...`) and Seerr still talks to `jellyfin:8096`.
Ollama models aren't copied; `ollama-models.service` pulls `OLLAMA_MODELS`.

**Rotate keys at this point** if you haven't: put the new ones in `secrets.env` and re-render.

## 3. Cut over

* Router DHCP DNS → new `LAN_IP`. Delete the `/etc/hosts` lines on the Mac/Pop.
* Neptune: change the server address. Ollama is now `http://LAN_IP:11434`.

## 4. Roll back the Pop box

```bash
# stop and remove the rootless stack
systemctl --user disable --now riven zurg-mount backup.timer 2>/dev/null
for s in caddy adguard jellyfin seerr zurg riven-db riven-redis ollama open-webui; do systemctl --user stop $s; done
rm ~/.config/containers/systemd                 # the symlink
rm -f ~/.config/systemd/user/{riven,zurg-mount,backup}.{service,timer}
systemctl --user daemon-reload
podman secret rm cf_api_token riven_db_pw
podman system reset                             # removes ALL rootless images/containers: only if nothing else uses podman
sudo loginctl disable-linger $USER

# system pieces
sudo systemctl disable --now homelab-mnt-shared.service
sudo rm /etc/systemd/system/homelab-mnt-shared.service && sudo systemctl daemon-reload
sudo sed -i '/^user_allow_other/d' /etc/fuse.conf
sudo rm -f /etc/cdi/nvidia.json
sudo systemctl unmask nvidia-cdi-refresh.path nvidia-cdi-refresh.service 2>/dev/null
sudo apt purge nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container1 libnvidia-container-tools \
  golang-github-containernetworking-plugin-dnsname rclone restic libfuse-dev
sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
sudo apt autoremove
# optional: build-essential pkg-config libfuse2t64 fuse3 (other software may need them), nvm (rm -rf ~/.nvm), ~/apps/riven-ts
sudo sed -i '/katieredihouse\.com/d' /etc/hosts
```

Keep `~/homelab` (it's this repo's ancestor) until the mini PC has run a week and a backup has been tested.
