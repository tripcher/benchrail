.PHONY: unit lint format build check-dist check-mac-m4 docker-buildx-setup docker-build-universal docker-publish-universal

DOCKER_REGISTRY ?= ghcr.io
DOCKER_IMAGE_OWNER ?= tripcher
DOCKER_IMAGE_NAME ?= benchrail-universal
DOCKER_IMAGE ?= $(DOCKER_REGISTRY)/$(DOCKER_IMAGE_OWNER)/$(DOCKER_IMAGE_NAME)
DOCKER_TAG ?= latest
DOCKER_LOCAL_PLATFORM ?= linux/arm64
DOCKER_PUBLISH_PLATFORMS ?= linux/amd64,linux/arm64

unit:
	uv run pytest tests/unit/ -v

lint:
	uv run ruff check benchrail/ tests/
	uv run mypy benchrail tests

format:
	uv run ruff format benchrail/ tests/
	uv run ruff check --fix benchrail/ tests/

build:
	uv run python -m build

check-dist:
	uv run twine check dist/*


docker-build-universal:
	docker buildx build --platform $(DOCKER_LOCAL_PLATFORM) -f docker/universal/Dockerfile -t $(DOCKER_IMAGE):$(DOCKER_TAG) --load .

docker-publish-universal:
	docker buildx build --platform $(DOCKER_PUBLISH_PLATFORMS) -f docker/universal/Dockerfile -t $(DOCKER_IMAGE):$(DOCKER_TAG) --push .
