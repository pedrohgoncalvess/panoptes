"""Remove generated project caches, keeping dependencies and private tool folders."""

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".uv-cache",
    ".cache",
    ".hypothesis",
}
PRESERVE = {".git", ".venv", "venv", "node_modules", ".agents", ".codex", ".aws"}


def clean_caches(root: Path = ROOT) -> list[Path]:
    root = root.resolve(strict=True)
    removed = []
    for parent, directories, _ in os.walk(root, topdown=True, followlinks=False):
        for name in list(directories):
            path = Path(parent) / name
            if name in PRESERVE or path.is_symlink() or path.is_junction():
                directories.remove(name)
                continue
            if name not in CACHE_NAMES and not name.startswith(".pytest-tmp"):
                continue
            target = path.resolve(strict=True)
            if target == root or not target.is_relative_to(root):
                raise ValueError(f"Cache outside workspace: {path}")
            # Every recursive deletion is checked against the resolved workspace.
            shutil.rmtree(target)
            removed.append(target)
            directories.remove(name)
    return removed


if __name__ == "__main__":
    for path in clean_caches():
        print(f"Removed: {path.relative_to(ROOT)}")
