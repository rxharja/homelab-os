IMAGE ?= localhost/homelab-os:latest
OWNER ?= OWNER
BOUND_IMAGES ?= 1

check-owner:
	@test "$(OWNER)" != OWNER || { \
	  echo "OWNER is unset, so caddy would be baked in as ghcr.io/owner/." >&2; \
	  echo "Example: make iso OWNER=rxharja" >&2; exit 1; }

build: check-owner  ## build the OS image locally
	sudo podman build --build-arg IMAGE_OWNER=$(OWNER) \
	  --build-arg BOUND_IMAGES=$(BOUND_IMAGES) -t $(IMAGE) .

caddy: check-owner  ## build the caddy-cloudflare image locally
	# sudo: bootc-image-builder reads root's container storage.
	sudo podman build -t ghcr.io/$(OWNER)/caddy-cloudflare:latest images/caddy

# Bound images fill the installer's RAM; quadlets pull them on first boot instead.
# The first bootc upgrade to the CI image binds them again.
iso: BOUND_IMAGES = 0
iso: build        ## installer ISO in ./output (rootful podman required)
	mkdir -p output
	sudo podman run --rm -it --privileged --pull=newer \
	  --security-opt label=type:unconfined_t \
	  -v ./bootc/config.toml:/config.toml:ro \
	  -v ./output:/output \
	  -v /var/lib/containers/storage:/var/lib/containers/storage \
	  quay.io/centos-bootc/bootc-image-builder:latest \
	  --type anaconda-iso --rootfs xfs --local $(IMAGE)

# Bound images break the bib install step. Override: make qcow2 BOUND_IMAGES=1
qcow2: BOUND_IMAGES = 0
qcow2: build      ## VM disk for a dry run in virt-manager/GNOME Boxes
	mkdir -p output
	sudo podman run --rm -it --privileged --pull=newer \
	  --security-opt label=type:unconfined_t \
	  -v ./bootc/config-vm.toml:/config.toml:ro \
	  -v ./output:/output \
	  -v /var/lib/containers/storage:/var/lib/containers/storage \
	  quay.io/centos-bootc/bootc-image-builder:latest \
	  --type qcow2 --rootfs xfs --local $(IMAGE)

lint:
	shellcheck -S warning rootfs/usr/bin/homelab-* scripts/export-devbox.sh
	python3 -m json.tool rootfs/etc/homelab/ranking.json >/dev/null

.PHONY: check-owner build caddy iso qcow2 lint
