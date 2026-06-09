from pathlib import Path

from benchrail.runner.environment import copy_environment_layers


def test_copy_environment_layers_overlays_instance_on_dataset(tmp_path: Path) -> None:
    dataset_env = tmp_path / "dataset" / "environment"
    instance_env = tmp_path / "dataset" / "task-1" / "environment"
    dst_env = tmp_path / "workspace" / "environment"

    dataset_env.mkdir(parents=True)
    instance_env.mkdir(parents=True)

    (dataset_env / "shared.txt").write_text("dataset\n", encoding="utf-8")
    (dataset_env / "dataset-only.txt").write_text("keep\n", encoding="utf-8")
    (dataset_env / "scripts").mkdir()
    (dataset_env / "scripts" / "setup.sh").write_text("echo dataset\n", encoding="utf-8")

    (instance_env / "shared.txt").write_text("instance\n", encoding="utf-8")
    (instance_env / "instance-only.txt").write_text("add\n", encoding="utf-8")
    (instance_env / "scripts" / "setup.sh").parent.mkdir()
    (instance_env / "scripts" / "setup.sh").write_text("echo instance\n", encoding="utf-8")

    copy_environment_layers([dataset_env, instance_env], dst_env)

    assert (dst_env / "shared.txt").read_text(encoding="utf-8") == "instance\n"
    assert (dst_env / "dataset-only.txt").read_text(encoding="utf-8") == "keep\n"
    assert (dst_env / "instance-only.txt").read_text(encoding="utf-8") == "add\n"
    assert (dst_env / "scripts" / "setup.sh").read_text(encoding="utf-8") == "echo instance\n"
