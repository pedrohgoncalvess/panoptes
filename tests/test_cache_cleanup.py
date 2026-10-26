import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "clean_caches", ROOT / "scripts/clean_caches.py"
)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def test_clean_caches_preserves_dependencies_and_source(tmp_path):
    for name in [
        "package/__pycache__",
        ".pytest_cache",
        ".pytest-tmp-run-123",
        ".uv-cache",
        ".venv/__pycache__",
        ".codex/.cache",
        "node_modules/.cache",
        "source",
    ]:
        path = tmp_path / name
        path.mkdir(parents=True)
        (path / "file").write_text("keep or remove")
    removed = cleanup.clean_caches(tmp_path)
    assert len(removed) == 4
    assert not (tmp_path / "package/__pycache__").exists()
    for name in [".venv/__pycache__", ".codex/.cache", "node_modules/.cache", "source"]:
        assert (tmp_path / name / "file").is_file()


def test_cleanup_checks_resolved_path_before_recursive_delete(tmp_path, monkeypatch):
    cache = tmp_path / ".cache"
    cache.mkdir()
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        return tmp_path.parent if path == cache else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="outside workspace"):
        cleanup.clean_caches(tmp_path)
    assert cache.is_dir()
