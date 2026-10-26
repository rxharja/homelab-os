# First boot (fresh, no migration)

0. **Password**: `ssh homelab@LAN_IP` (key-only; the installer sets no password), then
   `sudo passwd homelab`. Cockpit at `https://LAN_IP:9090` authenticates against it via PAM,
   so without this there's no admin UI and no console login.
1. **Router**: DHCP reservation for the mini PC, matching `LAN_IP`.
2. **Config**: fill `/etc/homelab/homelab.env` and `secrets.env` (see README). Use NEW tokens:
   the RD, TMDB, Seerr and Jellyfin keys pasted in chat earlier must be rotated.
3. `sudo systemctl restart homelab-render`, then `sudo homelab-status`.
4. **AdGuard**: browse `http://LAN_IP:3001` once for its setup wizard (leave its web port at 3000 and its DNS port at 53) (later it's
   `https://adguard.DOMAIN`). Add the rewrite `*.DOMAIN → LAN_IP` and `DOMAIN → LAN_IP`.
   Set upstreams (e.g. `https://dns.quad9.net/dns-query`).
5. **Router DHCP DNS** → `LAN_IP` (keep a public secondary only if you accept ads leaking through).
6. **Jellyfin** (`jellyfin.DOMAIN`): admin user; libraries Movies `/media/riven/movies` and
   Shows `/media/riven/shows`. Real-time monitoring, chapter images and trickplay off.
   Scheduled library scan hourly. Dashboard → API Keys → new key → `JELLYFIN_API_KEY`.
7. **Seerr** (`seerr.DOMAIN`): sign in with Jellyfin (host `jellyfin`, port `8096`), external
   URL `https://jellyfin.DOMAIN`, TV/Anime metadata = TVDB, auto-approve on.
   Settings → General → API key → `SEERR_API_KEY`.
8. **Comet**: put its settings in `/etc/homelab/riven.extra.env`.
9. `sudo systemctl restart homelab-render riven` and request something.
10. **Open WebUI** (`chat.DOMAIN`): first account = admin, then disable signups in Admin settings.
    Turn off tools for the small models (that was the `create_tasks` junk).
11. **Paperless** (`docs.DOMAIN`): `PAPERLESS_DB_PASSWORD`, `PAPERLESS_SECRET_KEY` and
    `PAPERLESS_URL` must be set before boot or `homelab-render` holds every container back.
    Create the admin with `sudo podman exec -it paperless python3 manage.py createsuperuser`.
    My Profile → API Auth Token → `PAPERLESS_API_TOKEN`, then
    `sudo systemctl restart homelab-render paperless-gpt`. Tag a document `paperless-gpt`
    to review suggestions at `sort.DOMAIN`, or `paperless-gpt-auto` to apply them.
12. **Actual** (`budget.DOMAIN`): set the server password on first visit, then create or import a budget.
    Bank sync (SimpleFIN/GoCardless) is optional, under Settings. Once the categories are
    final (`scripts/suggest-categories.py` proposes a set), set `ACTUAL_PASSWORD` in
    `secrets.env`, copy `examples/actual-ai.env` to `/etc/homelab/actual-ai.env` and fill it in, then
    `sudo systemctl restart homelab-render && sudo systemctl start actual-ai`.
13. **Pocket ID** (`id.DOMAIN`): `POCKET_ID_ENCRYPTION_KEY` must be set before boot. Open
    `https://id.DOMAIN/setup` to create the admin and register a passkey, then invite the household.
    Open WebUI: Pocket ID > OIDC Clients > Add, callback `https://chat.DOMAIN/oauth/oidc/callback`,
    then `OPEN_WEBUI_OIDC_CLIENT_ID`/`_SECRET` and `sudo systemctl restart homelab-render open-webui`.
14. **Neptune**: Jellyfin `https://jellyfin.DOMAIN` (or `http://LAN_IP:8096`), Ollama `http://LAN_IP:11434`.
15. **Backups**: set `RESTIC_*`, run `sudo systemctl start homelab-backup` once, then test a
    restore of one file: `restic restore latest --target /tmp/t --include /etc/homelab`.
