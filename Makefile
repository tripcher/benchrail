.PHONY: unit lint format build check-dist print-version print-release-tag bump bump-major bump-minor bump-patch tag-release docker-buildx-setup docker-build-universal docker-publish-universal

DOCKER_REGISTRY ?= ghcr.io
DOCKER_IMAGE_OWNER ?= tripcher
DOCKER_IMAGE_NAME ?= benchrail-universal
DOCKER_IMAGE ?= $(DOCKER_REGISTRY)/$(DOCKER_IMAGE_OWNER)/$(DOCKER_IMAGE_NAME)
DOCKER_TAG ?= latest
DOCKER_LOCAL_PLATFORM ?= linux/arm64
DOCKER_PUBLISH_PLATFORMS ?= linux/amd64,linux/arm64
BUMP ?= patch

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

print-version:
	@.venv/bin/python -c "from benchrail.versioning import read_version; print(read_version())"

print-release-tag:
	@.venv/bin/python -c "from benchrail.versioning import release_tag; print(release_tag())"

bump:
	.venv/bin/python -m benchrail.versioning $(BUMP)

bump-major:
	.venv/bin/python -m benchrail.versioning major

bump-minor:
	.venv/bin/python -m benchrail.versioning minor

bump-patch:
	.venv/bin/python -m benchrail.versioning patch

tag-release:
	git tag "$$(.venv/bin/python -c 'from benchrail.versioning import release_tag; print(release_tag())')"


docker-build-universal:
	docker buildx build --platform $(DOCKER_LOCAL_PLATFORM) -f docker/universal/Dockerfile -t $(DOCKER_IMAGE):$(DOCKER_TAG) --load .

docker-publish-universal:
	docker buildx build --platform $(DOCKER_PUBLISH_PLATFORMS) -f docker/universal/Dockerfile -t $(DOCKER_IMAGE):$(DOCKER_TAG) --push .
