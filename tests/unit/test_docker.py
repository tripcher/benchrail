from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from benchrail.runner import docker as docker_runner
from benchrail.runner.logging_util import RunnerLogger


class _ClosableExecStream:
    def __init__(
        self,
        events: list[tuple[str, object]],
        chunks: list[tuple[bytes | None, bytes | None]] | None = None,
    ) -> None:
        self._events = events
        self._chunks = chunks or []
        self._response = _ClosableExecResponse(events)

    def __iter__(self) -> Iterator[tuple[bytes | None, bytes | None]]:
        yield from self._chunks

    def close(self) -> None:
        self._events.append(("exec_stream_close", None))


class _ClosableExecResponse:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self._events = events

    def close(self) -> None:
        self._events.append(("exec_response_close", None))


class _ClosableBuildLogs:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self._events = events

    def __iter__(self) -> Iterator[dict[str, str]]:
        yield {"stream": "building...\n"}

    def close(self) -> None:
        self._events.append(("build_logs_close", None))


class _FakeAPI:
    def __init__(self, events: list[tuple[str, object]], exit_code: int = 0) -> None:
        self.events = events
        self.exit_code = exit_code

    def exec_create(
        self,
        container: str,
        cmd: list[str],
        *,
        workdir: str,
        environment: list[str],
    ) -> dict[str, str]:
        self.events.append(("exec_create", cmd))
        return {"Id": "exec-1"}

    def exec_start(
        self,
        exec_id: str,
        *,
        stream: bool,
        demux: bool,
    ) -> _ClosableExecStream:
        self.events.append(("exec_start", exec_id))
        return _ClosableExecStream(self.events)

    def exec_inspect(self, exec_id: str) -> dict[str, int]:
        self.events.append(("exec_inspect", exec_id))
        return {"ExitCode": self.exit_code}

    def put_archive(self, container: str, path: str, data: object) -> bool:
        self.events.append(("put_archive", path))
        return True


class _FakeContainer:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events
        self.id = "container-1"
        self.status = "created"

    def start(self, **kwargs: object) -> None:
        self.events.append(("start", None))
        self.status = "running"

    def reload(self) -> None:
        self.events.append(("reload", None))

    def stop(self, timeout: int = 10, **kwargs: object) -> None:
        self.events.append(("stop", timeout))

    def remove(self, force: bool = False, **kwargs: object) -> None:
        self.events.append(("remove", force))


class _FakeContainers:
    def __init__(self, container: _FakeContainer, events: list[tuple[str, object]]) -> None:
        self.container = container
        self.events = events

    def create(self, *args: object, **kwargs: object) -> _FakeContainer:
        self.events.append(("create", (kwargs.get("working_dir"), kwargs.get("init"))))
        return self.container


class _FakeImages:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def build(self, **kwargs: object) -> tuple[object, _ClosableBuildLogs]:
        self.events.append(("build", kwargs["tag"]))
        return object(), _ClosableBuildLogs(self.events)


class _FakeClient:
    def __init__(self, events: list[tuple[str, object]], exit_code: int = 0) -> None:
        self.events = events
        self.api = _FakeAPI(events, exit_code)
        self.containers = _FakeContainers(_FakeContainer(events), events)
        self.images = _FakeImages(events)

    def close(self) -> None:
        self.events.append(("client_close", None))


def test_create_task_runner_starts_and_prepares_dirs_before_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[tuple[str, object]] = []
    fake_client = _FakeClient(events)
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    bench_env = tmp_path / "environment"
    bench_env.mkdir()
    (bench_env / "setup.sh").write_text("echo setup\n", encoding="utf-8")
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "test.patch").write_text("", encoding="utf-8")

    logger = RunnerLogger(tmp_path / "runner.log")
    runner = docker_runner.create_task_runner(
        "benchrail-universal:latest",
        bench_env,
        patches,
        {"CODEX_API_KEY": "secret"},
        logger,
    )

    assert runner is not None
    assert events == [
        ("create", ("/", True)),
        ("start", None),
        ("reload", None),
        ("exec_create", ["mkdir", "-p", "/bench/environment", "/bench/patches", "/bench/repo"]),
        ("exec_start", "exec-1"),
        ("exec_response_close", None),
        ("exec_inspect", "exec-1"),
        ("put_archive", "/bench/environment/"),
        ("put_archive", "/bench/patches/"),
    ]


def test_runner_exec_closes_underlying_response_and_client_on_teardown(
    tmp_path: Path,
) -> None:
    events: list[tuple[str, object]] = []
    fake_client = _FakeClient(events)
    container = _FakeContainer(events)
    logger = RunnerLogger(tmp_path / "runner.log")
    runner = docker_runner.DockerTaskRunner(
        cast(docker_runner._DockerClient, fake_client),
        container,
        "image:latest",
        logger,
    )

    result = runner.exec(
        ["echo", "hello"],
        workdir="/bench/repo",
        env={},
        timeout=5,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        event_name="TEST_STEP",
    )
    runner.stop_and_remove()

    assert result.exit_code == 0
    assert ("exec_response_close", None) in events
    assert ("exec_stream_close", None) not in events
    assert ("client_close", None) in events
    assert events[0] == (
        "exec_create",
        ["timeout", "--kill-after=5s", "5s", "bash", "--login", "-lc", "echo hello"],
    )


def test_runner_exec_reports_container_side_timeout(tmp_path: Path) -> None:
    events: list[tuple[str, object]] = []
    fake_client = _FakeClient(events, exit_code=124)
    container = _FakeContainer(events)
    logger = RunnerLogger(tmp_path / "runner.log")
    runner = docker_runner.DockerTaskRunner(
        cast(docker_runner._DockerClient, fake_client),
        container,
        "image:latest",
        logger,
    )

    result = runner.exec(
        ["sleep", "10"],
        workdir="/bench/repo",
        env={},
        timeout=3,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        event_name="TEST_STEP",
    )

    assert result.exit_code == -1
    assert result.timed_out is True
    assert events[0] == (
        "exec_create",
        ["timeout", "--kill-after=5s", "3s", "bash", "--login", "-lc", "sleep 10"],
    )


def test_build_image_closes_logs_and_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[tuple[str, object]] = []
    fake_client = _FakeClient(events)
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    ok = docker_runner.build_image(
        context_dir=tmp_path,
        dockerfile_rel="Dockerfile",
        image_tag="benchrail:test",
        logs_dir=tmp_path,
        logger=RunnerLogger(tmp_path / "runner.log"),
    )

    assert ok is True
    assert ("build_logs_close", None) in events
    assert ("client_close", None) in events
