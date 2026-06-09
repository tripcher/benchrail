"""Shared host-side environment staging helpers."""

from __future__ import annotations

import shutil
from pathlib import Path


def copy_environment(src_dir: Path, dst_dir: Path) -> None:
    """Copy all files from src_dir to dst_dir."""
    if not src_dir.exists():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        dst = dst_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)


def copy_environment_layers(src_dirs: list[Path], dst_dir: Path) -> None:
    """Copy environment directories in order, letting later sources replace earlier files."""
    for src_dir in src_dirs:
        copy_environment(src_dir, dst_dir)
