# The whole server as one image. Build:  podman build -t homelab-os .
# Deploy:  bootc-image-builder (ISO/qcow2) or `bootc switch ghcr.io/<you>/homelab-os`
ARG FEDORA_VERSION=44
FROM quay.io/fedora/fedora-bootc:${FEDORA_VERSION}

# GitHub owner for ghcr.io/<owner>/caddy-cloudflare (set by CI).
ARG IMAGE_OWNER=OWNER

# 0 skips bound images: bootc-image-builder fails to resolve them against a
# read-only containers-storage. The qcow2 dry run sets this.
ARG BOUND_IMAGES=1

RUN dnf -y install 'dnf5-command(config-manager)' \
 && dnf config-manager addrepo --from-repofile=https://pkgs.tailscale.com/stable/fedora/tailscale.repo \
 && dnf -y install \
      tailscale rclone restic fuse3 gettext-envsubst \
      cockpit cockpit-podman cockpit-storaged cockpit-networkmanager \
      firewalld mesa-vulkan-drivers zstd jq htop curl \
 && dnf clean all && rm -rf /var/cache/* /var/log/*

COPY rootfs/ /

RUN set -eux; \
    sed -i "s|ghcr.io/OWNER/|ghcr.io/${IMAGE_OWNER,,}/|" /usr/share/containers/systemd/caddy.container; \
    # Bound images are pulled during install/upgrade, so a new OS never boots
    # without its containers.
    if [ "${BOUND_IMAGES}" = 1 ]; then \
      mkdir -p /usr/lib/bootc/bound-images.d; \
      for f in /usr/share/containers/systemd/*.container; do \
        ln -s "$f" /usr/lib/bootc/bound-images.d/; \
      done; \
    fi; \
    # UserNS=auto draws from the 'containers' range.
    grep -q '^containers:' /etc/subuid || echo 'containers:2147483647:2147483648' >>/etc/subuid; \
    grep -q '^containers:' /etc/subgid || echo 'containers:2147483647:2147483648' >>/etc/subgid; \
    # AdGuard owns :53, so point resolv.conf at the real upstream list.
    ln -sf ../run/systemd/resolve/resolv.conf /etc/resolv.conf; \
    # secrets.env lands here; tmpfiles.d re-asserts this on every boot.
    chmod 0750 /etc/homelab; \
    # git can't track 0440, and sudo ignores a group-writable sudoers file.
    chmod 0440 /etc/sudoers.d/10-wheel-nopasswd; \
    visudo -cqf /etc/sudoers; \
    # Host services only. Podman's published ports bypass firewalld (netavark
    # writes its own nftables rules).
    firewall-offline-cmd --add-service={ssh,dns,http,https,cockpit}; \
    firewall-offline-cmd --add-port={8096,11434,3001}/tcp; \
    systemctl enable tailscaled.service cockpit.socket firewalld.service \
      podman-auto-update.timer homelab-media-mount.service homelab-render.service \
      zurg-mount.service ollama-models.service homelab-backup.timer

RUN bootc container lint
