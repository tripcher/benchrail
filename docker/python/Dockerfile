# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04 AS base

ENV LANG="C.UTF-8"
ENV HOME=/root
ENV DEBIAN_FRONTEND=noninteractive

### BASE ###

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential=12.10* \
        ca-certificates=20240203 \
        curl=8.5.* \
        git=1:2.43.* \
        libbz2-dev=1.0.* \
        libffi-dev=3.4.* \
        liblzma-dev=5.6.* \
        libncurses-dev=6.4+20240113-* \
        libreadline-dev=8.2-* \
        libsqlite3-dev=3.45.* \
        libssl-dev=3.0.* \
        make=4.3-* \
        pipx=1.4.* \
        pkg-config=1.8.* \
        tk-dev=8.6.* \
        tzdata=2026a-* \
        xz-utils=5.6.* \
        zlib1g-dev=1:1.3.* \
    && rm -rf /var/lib/apt/lists/*

### PYTHON ###

ARG PYTHON_VERSIONS="3.14 3.13 3.12 3.11 3.10"

ENV PYENV_ROOT=/root/.pyenv
ENV PATH=/root/.local/bin:/root/.pyenv/shims:/root/.pyenv/bin:$PATH

RUN git -c advice.detachedHead=0 clone --depth 1 https://github.com/pyenv/pyenv.git "$PYENV_ROOT" \
    && echo 'export PYENV_ROOT="$HOME/.pyenv"' >> /etc/profile \
    && echo 'export PATH="$PYENV_ROOT/shims:$PYENV_ROOT/bin:/root/.local/bin:$PATH"' >> /etc/profile \
    && echo 'eval "$(pyenv init - bash)"' >> /etc/profile \
    && cd "$PYENV_ROOT" \
    && src/configure \
    && make -C src \
    && pyenv install $PYTHON_VERSIONS \
    && pyenv global "${PYTHON_VERSIONS%% *}" \
    && rm -rf "$PYENV_ROOT/cache"

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/pipx \
    pipx install --pip-args="--no-cache-dir --no-compile --root-user-action=ignore" poetry==2.1.* uv==0.7.* \
    && for pyv in "${PYENV_ROOT}/versions/"*; do \
         "$pyv/bin/python" -m pip install --no-cache-dir --no-compile --root-user-action=ignore --upgrade pip setuptools; \
       done

ENV UV_NO_PROGRESS=1

### NODE ###

ARG NVM_VERSION=v0.40.2
ARG NODE_VERSION=22

ENV NVM_DIR=/root/.nvm
ENV COREPACK_DEFAULT_TO_LATEST=0
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
ENV COREPACK_ENABLE_AUTO_PIN=0
ENV COREPACK_ENABLE_STRICT=0

RUN --mount=type=cache,target=/root/.npm \
    --mount=type=cache,target=/root/.cache/yarn \
    --mount=type=cache,target=/root/.local/share/pnpm/store \
    git -c advice.detachedHead=0 clone --branch "$NVM_VERSION" --depth 1 https://github.com/nvm-sh/nvm.git "$NVM_DIR" \
    && echo 'source $NVM_DIR/nvm.sh' >> /etc/profile \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install "$NODE_VERSION" \
    && nvm alias default "$NODE_VERSION" \
    && nvm use "$NODE_VERSION" \
    && npm install -g npm@11.4 pnpm@10.12 \
    && corepack enable \
    && corepack install -g yarn \
    && nvm cache clear \
    && npm cache clean --force || true \
    && pnpm store prune || true \
    && yarn cache clean || true

### AGENT CLIS ###

ARG BENCH_ENV_CODEX_VERSION=""
ARG BENCH_ENV_CLAUDE_CODE_VERSION=""

ENV BENCH_ENV_CODEX_VERSION="${BENCH_ENV_CODEX_VERSION}"
ENV BENCH_ENV_CLAUDE_CODE_VERSION="${BENCH_ENV_CLAUDE_CODE_VERSION}"

### SETUP SCRIPTS ###

COPY docker/python/setup_python.sh /opt/benchrail/setup_python.sh
RUN chmod +x /opt/benchrail/setup_python.sh

COPY docker/python/setup_agents.sh /opt/benchrail/setup_agents.sh
RUN chmod +x /opt/benchrail/setup_agents.sh

### VERIFICATION SCRIPT ###

COPY docker/python/verify.sh /opt/verify.sh
RUN chmod +x /opt/verify.sh \
    && PYTHON_VERSIONS="$PYTHON_VERSIONS" \
        NODE_VERSION="$NODE_VERSION" \
        /opt/verify.sh

### ENTRYPOINT ###

COPY docker/python/entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh

ENTRYPOINT ["/opt/entrypoint.sh"]

FROM base AS runner

COPY pyproject.toml README.md uv.lock /opt/benchrail/
COPY benchrail /opt/benchrail/benchrail

RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install /opt/benchrail \
    && benchrail --help >/dev/null
