# The whole server as one image. Build:  podman build -t homelab-os .
# Deploy:  bootc-image-builder (ISO/qcow2) or `bootc switch ghcr.io/<you>/homelab-os`
ARG FEDORA_VERSION=44
FROM quay.io/fedora/fedora-bootc:${FEDORA_VERSION}

# GitHub owner for ghcr.io/<owner>/caddy-cloudflare (set by CI).
ARG IMAGE_OWNER=OWNER

RUN dnf -y install 'dnf5-command(config-manager)' \
 && dnf config-manager addrepo --from-repofile=https://pkgs.tailscale.com/stable/fedora/tailscale.repo \
 && dnf -y install \
      tailscale rclone restic fuse3 gettext-envsubst \
      cockpit cockpit-podman cockpit-storaged cockpit-networkmanager \
      firewalld mesa-vulkan-drivers zstd jq htop curl \
 && dnf clean all && rm -rf /var/cache/* /var/log/*

# Everything static: Quadlets, host units, scripts, tmpfiles/sysctl/resolved
# drop-ins, the Caddyfile, and the default ranking.json in /etc.
COPY rootfs/ /

RUN set -eux; \
    sed -i "s|ghcr.io/OWNER/|ghcr.io/${IMAGE_OWNER,,}/|" /usr/share/containers/systemd/caddy.container; \
    # Logically bound images: pulled during install/upgrade, so a new OS never
    # boots without its containers present.
    mkdir -p /usr/lib/bootc/bound-images.d; \
    for f in /usr/share/containers/systemd/*.container; do \
      ln -s "$f" /usr/lib/bootc/bound-images.d/; \
    done; \
    # UserNS=auto draws from the 'containers' range.
    grep -q '^containers:' /etc/subuid || echo 'containers:2147483647:2147483648' >>/etc/subuid; \
    grep -q '^containers:' /etc/subgid || echo 'containers:2147483647:2147483648' >>/etc/subgid; \
    # AdGuard owns :53, so point resolv.conf at the real upstream list.
    ln -sf ../run/systemd/resolve/resolv.conf /etc/resolv.conf; \
    # secrets.env lands here. tmpfiles.d re-asserts 0750 on every boot; set it
    # now too, so it's never world-readable before that first run.
    chmod 0750 /etc/homelab; \
    # Host services. Podman's published ports bypass firewalld (netavark
    # nftables), but Jellyfin/Ollama/AdGuard are listed for documentation.
    firewall-offline-cmd --add-service={ssh,dns,http,https,cockpit}; \
    firewall-offline-cmd --add-port={8096,11434,3001}/tcp; \
    systemctl enable tailscaled.service cockpit.socket firewalld.service \
      podman-auto-update.timer homelab-media-mount.service homelab-render.service \
      zurg-mount.service ollama-models.service homelab-backup.timer

RUN bootc container lint
