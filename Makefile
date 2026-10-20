IMAGE ?= localhost/homelab-os:latest
OWNER ?= OWNER

build:            ## build the OS image locally
	sudo podman build --build-arg IMAGE_OWNER=$(OWNER) -t $(IMAGE) .

caddy:            ## build the caddy-cloudflare image locally
	podman build -t ghcr.io/$(OWNER)/caddy-cloudflare:latest images/caddy

iso: build        ## installer ISO in ./output (rootful podman required)
	mkdir -p output
	sudo podman run --rm -it --privileged --pull=newer \
	  --security-opt label=type:unconfined_t \
	  -v ./bootc/config.toml:/config.toml:ro \
	  -v ./output:/output \
	  -v /var/lib/containers/storage:/var/lib/containers/storage \
	  quay.io/centos-bootc/bootc-image-builder:latest \
	  --type anaconda-iso --rootfs xfs --local $(IMAGE)

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

.PHONY: build caddy iso qcow2 lint
