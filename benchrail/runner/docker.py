"""Docker executor: builds images and runs lifecycle steps inside containers."""

from __future__ import annotations

import re
import shlex
import time
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict, cast

from benchrail.runner.logging_util import RunnerLogger, TruncatingWriter


def _sanitize_tag(value: str) -> str:
    """Make a string safe for use in Docker image/container names."""
    return re.sub(r"[^a-zA-Z0-9._-]", "-", value).lower().strip("-")


@dataclass
class StepResult:
    exit_code: int
    duration_ms: int
    timed_out: bool = False
    stderr_tail: str = ""


def _tail(data: bytes, max_bytes: int = 500) -> str:
    tail = data[-max_bytes:] if len(data) > max_bytes else data
    return tail.decode("utf-8", errors="replace").strip()


class _DockerExecCreateResult(TypedDict):
    Id: str


class _DockerExecInspectResult(TypedDict, total=False):
    ExitCode: int


class _DockerLogChunk(TypedDict, total=False):
    stream: str
    error: str


class _DockerExecStream(Protocol):
    def __iter__(self) -> Iterator[tuple[bytes | None, bytes | None]]: ...

    def __next__(self) -> tuple[bytes | None, bytes | None]: ...

    def close(self) -> None: ...


class _DockerAPI(Protocol):
    def exec_create(
        self,
        container: str,
        cmd: list[str],
        *,
        workdir: str,
        environment: list[str],
    ) -> _DockerExecCreateResult: ...

    def exec_start(
        self,
        exec_id: str,
        *,
        stream: bool,
        demux: bool,
    ) -> _DockerExecStream: ...

    def exec_inspect(self, exec_id: str) -> _DockerExecInspectResult: ...

    def put_archive(self, container: str, path: str, data: object) -> bool: ...


class _DockerClient(Protocol):
    api: _DockerAPI

    def close(self) -> None: ...


class _DockerContainer(Protocol):
    @property
    def id(self) -> str | None: ...

    def stop(self, timeout: int = 10, **kwargs: object) -> None: ...
    def remove(self, force: bool = False, **kwargs: object) -> None: ...
    def start(self, **kwargs: object) -> None: ...
    def reload(self) -> None: ...


def _close_quietly(obj: object) -> None:
    response = getattr(obj, "_response", None)
    response_close = getattr(response, "close", None)
    if callable(response_close):
        with suppress(Exception):
            response_close()
        return

    close = getattr(obj, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


class DockerTaskRunner:
    """Manages a single long-lived container for one task."""

    def __init__(
        self,
        client: _DockerClient,
        container: _DockerContainer,
        image_tag: str,
        logger: RunnerLogger,
    ) -> None:
        self._client = client
        self._container = container
        self._image_tag = image_tag
        self._logger = logger

    def exec(
        self,
        cmd: list[str],
        workdir: str,
        env: dict[str, str],
        timeout: int,
        stdout_path: Path,
        stderr_path: Path,
        event_name: str,
        log_extra: Mapping[str, object] | None = None,
    ) -> StepResult:
        extra = log_extra or {}
        self._logger.info(f"{event_name}_START", **extra)
        start = time.monotonic()

        stdout_w = TruncatingWriter(stdout_path, self._logger)
        stderr_w = TruncatingWriter(stderr_path, self._logger)

        exit_code = -1

        try:
            env_list = [f"{k}={v}" for k, v in env.items()]
            wrapped_cmd = [
                "timeout",
                "--kill-after=5s",
                f"{timeout}s",
                "bash",
                "--login",
                "-lc",
                shlex.join(cmd),
            ]
            container_id = self._container.id
            if container_id is None:
                raise ValueError("Container id is missing")
            exec_id = self._client.api.exec_create(
                container_id,
                wrapped_cmd,
                workdir=workdir,
                environment=env_list,
            )
            output_gen = self._client.api.exec_start(exec_id["Id"], stream=True, demux=True)

            stdout_buf: list[bytes] = []
            stderr_buf: list[bytes] = []

            try:
                for stdout_chunk, stderr_chunk in output_gen:
                    if stdout_chunk:
                        stdout_w.write(stdout_chunk)
                        stdout_buf.append(stdout_chunk)
                    if stderr_chunk:
                        stderr_w.write(stderr_chunk)
                        stderr_buf.append(stderr_chunk)
            finally:
                _close_quietly(output_gen)

            inspect = self._client.api.exec_inspect(exec_id["Id"])
            exit_code = inspect.get("ExitCode", -1)
            duration_ms = int((time.monotonic() - start) * 1000)

            stderr_data = b"".join(stderr_buf)
            stderr_tail_str = _tail(stderr_data) if exit_code != 0 else ""

            if exit_code in {124, 137}:
                self._logger.warn(
                    f"{event_name}_TIMEOUT",
                    elapsed_ms=duration_ms,
                    limit_ms=timeout * 1000,
                    stderr_tail=stderr_tail_str,
                )
                return StepResult(
                    exit_code=-1,
                    duration_ms=duration_ms,
                    timed_out=True,
                    stderr_tail=stderr_tail_str,
                )

            log_kw: dict[str, object] = {
                "duration_ms": duration_ms,
                "exit_code": exit_code,
                **extra,
            }
            if exit_code != 0:
                self._logger.error(f"{event_name}_FAILED", stderr_tail=stderr_tail_str, **log_kw)
            else:
                self._logger.info(f"{event_name}_END", **log_kw)

            return StepResult(
                exit_code=exit_code, duration_ms=duration_ms, stderr_tail=stderr_tail_str
            )

        finally:
            stdout_w.close()
            stderr_w.close()

    def stop_and_remove(self) -> None:
        try:
            self._logger.info("CONTAINER_STOP")
            self._container.stop(timeout=10)
        except Exception:
            pass
        try:
            self._logger.info("CONTAINER_REMOVE")
            self._container.remove(force=True)
        except Exception:
            pass
        _close_quietly(self._client)


def build_image(
    context_dir: Path,
    dockerfile_rel: str,
    image_tag: str,
    logs_dir: Path,
    logger: RunnerLogger,
) -> bool:
    """Build docker image. Returns True on success."""
    import docker

    client = docker.from_env()
    logger.info("BUILD_START", context=str(context_dir), dockerfile=dockerfile_rel, image=image_tag)
    start = time.monotonic()

    stdout_w = TruncatingWriter(logs_dir / "build.stdout", logger)
    stderr_w = TruncatingWriter(logs_dir / "build.stderr", logger)

    try:
        _, build_logs = client.images.build(
            path=str(context_dir),
            dockerfile=dockerfile_rel,
            tag=image_tag,
            rm=True,
        )
        try:
            for chunk in build_logs:
                if not isinstance(chunk, dict):
                    continue
                if "stream" in chunk and isinstance(chunk["stream"], str):
                    stdout_w.write(chunk["stream"].encode("utf-8", errors="replace"))
                if "error" in chunk and isinstance(chunk["error"], str):
                    stderr_w.write(chunk["error"].encode("utf-8", errors="replace"))
        finally:
            _close_quietly(build_logs)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("BUILD_END", duration_ms=duration_ms, exit_code=0)
        return True
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        err_msg = str(e)[:500]
        stderr_w.write(err_msg.encode("utf-8", errors="replace"))
        logger.error("BUILD_FAILED", duration_ms=duration_ms, error=err_msg[:200])
        return False
    finally:
        stdout_w.close()
        stderr_w.close()
        _close_quietly(client)


def create_task_runner(
    image_tag: str,
    bench_env_src: Path,
    patches_src: Path | None,
    container_env: dict[str, str],
    logger: RunnerLogger,
) -> DockerTaskRunner | None:
    """Create container, copy artifacts, start it. Returns runner or None on failure."""
    import docker

    client = docker.from_env()

    try:
        logger.info("CONTAINER_CREATE", image=image_tag)
        container = client.containers.create(
            image_tag,
            command=["sleep", "infinity"],
            detach=True,
            tty=True,
            environment=container_env,
            init=True,
            working_dir="/",
        )
        typed_client = cast(_DockerClient, client)
        typed_container = cast(_DockerContainer, container)

        logger.info("CONTAINER_START")
        container.start()
        if hasattr(container, "reload"):
            container.reload()
        status = getattr(container, "status", None)
        if status and status != "running":
            logger.error("CONTAINER_NOT_RUNNING", image=image_tag, status=status)
            with suppress(Exception):
                container.remove(force=True)
            return None

        _ensure_container_dirs(
            typed_client,
            typed_container,
            ["/bench/environment", "/bench/patches", "/bench/repo"],
        )

        # Copy environment/
        if bench_env_src.exists():
            logger.info("CONTAINER_CP", src=str(bench_env_src), dst="/bench/environment/")
            _cp_dir_to_container(
                typed_client,
                typed_container,
                bench_env_src,
                "/bench/environment/",
            )

        # Copy patches/ if any patch files exist
        if patches_src and patches_src.exists():
            logger.info("CONTAINER_CP", src=str(patches_src), dst="/bench/patches/")
            _cp_dir_to_container(typed_client, typed_container, patches_src, "/bench/patches/")
        return DockerTaskRunner(typed_client, typed_container, image_tag, logger)

    except Exception as e:
        logger.error("CONTAINER_CREATE_FAILED", error=str(e)[:200])
        return None


def copy_file_to_container(
    runner: DockerTaskRunner,
    src_file: Path,
    dst_dir: str,
    dst_relpath: str,
) -> None:
    runner._logger.info("CONTAINER_CP_FILE", src=str(src_file), dst=f"{dst_dir}/{dst_relpath}")
    _cp_file_to_container(runner._client, runner._container, src_file, dst_dir, dst_relpath)


def apply_patch(
    runner: DockerTaskRunner,
    patch_path: str,
    workdir: str,
    env: dict[str, str],
    logs_dir: Path,
    log_prefix: str,
) -> StepResult:
    precheck = runner.exec(
        ["git", "apply", "--check", patch_path],
        workdir=workdir,
        env=env,
        timeout=60,
        stdout_path=logs_dir / f"{log_prefix}.check.stdout",
        stderr_path=logs_dir / f"{log_prefix}.check.stderr",
        event_name=f"{log_prefix.upper()}_CHECK",
        log_extra={
            "path": patch_path,
            "check_only": True,
            "note": "patch applicability depends on repository state after agent changes",
        },
    )
    if precheck.exit_code != 0 or precheck.timed_out:
        runner._logger.error(
            f"{log_prefix.upper()}_PRECHECK_FAILED",
            path=patch_path,
            exit_code=precheck.exit_code,
            timed_out=precheck.timed_out,
            stderr_tail=precheck.stderr_tail,
            hint="test patch may conflict with agent changes or dataset patch surface",
        )
        return precheck

    return runner.exec(
        ["git", "apply", patch_path],
        workdir=workdir,
        env=env,
        timeout=60,
        stdout_path=logs_dir / f"{log_prefix}.stdout",
        stderr_path=logs_dir / f"{log_prefix}.stderr",
        event_name=log_prefix.upper(),
        log_extra={
            "path": patch_path,
            "check_only": False,
            "note": "patch applicability depends on repository state after agent changes",
        },
    )


def _cp_dir_to_container(
    client: _DockerClient,
    container: _DockerContainer,
    src_dir: Path,
    dst_path: str,
) -> None:
    """Tar a directory and copy it into a container."""
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(str(src_dir), arcname=".")
    buf.seek(0)
    if container.id is None:
        raise ValueError("Container id is missing")
    client.api.put_archive(container.id, dst_path, buf)


def _ensure_container_dirs(
    client: _DockerClient,
    container: _DockerContainer,
    paths: list[str],
) -> None:
    container_id = container.id
    if container_id is None:
        raise ValueError("Container id is missing")
    exec_id = client.api.exec_create(
        container_id,
        ["mkdir", "-p", *paths],
        workdir="/",
        environment=[],
    )
    output_gen = client.api.exec_start(exec_id["Id"], stream=True, demux=True)
    try:
        for _stdout_chunk, _stderr_chunk in output_gen:
            pass
    finally:
        _close_quietly(output_gen)
    result = client.api.exec_inspect(exec_id["Id"])
    if result.get("ExitCode", 1) != 0:
        raise RuntimeError(f"failed to create container directories: {paths}")


def _cp_file_to_container(
    client: _DockerClient,
    container: _DockerContainer,
    src_file: Path,
    dst_dir: str,
    dst_relpath: str,
) -> None:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(str(src_file), arcname=dst_relpath)
    buf.seek(0)
    if container.id is None:
        raise ValueError("Container id is missing")
    client.api.put_archive(container.id, dst_dir, buf)


def make_image_tag(run_id: str, agent_id: str, instance_id: str) -> str:
    run = _sanitize_tag(run_id)
    agent = _sanitize_tag(agent_id)
    instance = _sanitize_tag(instance_id)
    return f"bench-{run}-{agent}-{instance}"
