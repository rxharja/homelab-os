#!/usr/bin/env bash
# Run on the Pop!_OS dev box (rootless setup) to package state for the mini PC.
#   ./scripts/export-devbox.sh            -> ~/homelab-export.tar.zst
# Copy it over (scp) and run: sudo homelab-import homelab-export.tar.zst
set -euo pipefail
SRC=$HOME/homelab/appdata
OUT=${1:-$HOME/homelab-export.tar.zst}
STAGE=$(mktemp -d)
cleanup() { podman unshare rm -rf "$STAGE"; }
trap cleanup EXIT

mkdir -p "$STAGE/appdata" "$STAGE/meta"
ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' >"$STAGE/meta/lan_ip"

echo "dumping riven-db"
podman exec riven-db pg_dump -U riven --clean --if-exists --no-owner riven >"$STAGE/riven.sql"

echo "stopping SQLite apps for a clean copy"
systemctl --user stop seerr jellyfin open-webui
trap 'systemctl --user start seerr jellyfin open-webui; cleanup' EXIT

# podman unshare: rootless files may be owned by subuids we can't read directly.
podman unshare cp -a "$SRC/adguard" "$SRC/caddy" "$SRC/seerr" "$SRC/open-webui" "$STAGE/appdata/"
mkdir -p "$STAGE/appdata/jellyfin"
podman unshare cp -a "$SRC/jellyfin/config" "$STAGE/appdata/jellyfin/"
[[ -f $SRC/riven/.env.riven ]] && cp "$SRC/riven/.env.riven" "$STAGE/riven.env.devbox"

podman unshare tar --zstd -cf "$OUT" -C "$STAGE" .
chmod 600 "$OUT"
echo "wrote $OUT (contains secrets: delete it after import)"
