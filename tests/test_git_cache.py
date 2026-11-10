"""仓库分析基础能力的离线回归测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reposleuth_toolkit import clone_repo


def _local_repo(parent: Path, value: str) -> Path:
    root = parent / "same"
    root.mkdir(parents=True)
    (root / "marker.py").write_text(value, encoding="utf-8")
    return root


def test_same_named_sources_use_separate_cache_directories(tmp_path: Path) -> None:
    first = _local_repo(tmp_path / "alice", "ALICE = 1\n")
    second = _local_repo(tmp_path / "bob", "BOB = 1\n")
    cache = tmp_path / "cache"
    a = clone_repo(str(first), cache)
    b = clone_repo(str(second), cache)
    assert a.name == b.name == "same"
    assert Path(a.local_path).parent == cache.resolve()
    assert Path(a.local_path) != Path(b.local_path)
    assert (Path(b.local_path) / "marker.py").read_text(encoding="utf-8") == "BOB = 1\n"


def test_explicit_cache_name_rejects_other_source(tmp_path: Path) -> None:
    first = _local_repo(tmp_path / "alice", "ALICE = 1\n")
    second = _local_repo(tmp_path / "bob", "BOB = 1\n")
    cache = tmp_path / "cache"
    original = clone_repo(str(first), cache, name="shared")
    with pytest.raises(FileExistsError):
        clone_repo(str(second), cache, name="shared")
    assert "ALICE" in (Path(original.local_path) / "marker.py").read_text(encoding="utf-8")


def test_cache_reuses_verified_source_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _local_repo(tmp_path / "source", "VALUE = 1\n")
    first = clone_repo(str(source), tmp_path / "cache", name="verified")

    def no_copy(*args, **kwargs):
        raise AssertionError("已验证缓存不应再次复制")

    monkeypatch.setattr("reposleuth_toolkit.git_tool.shutil.copytree", no_copy)
    assert clone_repo(str(source), tmp_path / "cache", name="verified").local_path == first.local_path


def test_same_named_remote_repositories_are_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import reposleuth_toolkit.git_tool as git_tool

    cloned = []

    def fake_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        source, destination = args[-2:]
        root = Path(destination)
        root.mkdir()
        (root / "marker.py").write_text(source, encoding="utf-8")
        cloned.append(source)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(git_tool, "_github_size_mb", lambda url: None)
    monkeypatch.setattr(git_tool, "_run_git", fake_git)
    a = clone_repo("https://github.com/alice/same", tmp_path)
    b = clone_repo("https://github.com/bob/same", tmp_path)
    same_a = clone_repo("git@github.com:alice/same.git", tmp_path)
    assert a.local_path != b.local_path
    assert same_a.local_path == a.local_path
    assert cloned == ["https://github.com/alice/same", "https://github.com/bob/same"]
    assert "bob/same" in (Path(b.local_path) / "marker.py").read_text(encoding="utf-8")


def test_verified_cache_rechecks_size_limits(tmp_path: Path) -> None:
    from reposleuth_toolkit import RepoTooLarge

    source = _local_repo(tmp_path / "source", "VALUE = 1\n")
    original = clone_repo(str(source), tmp_path / "cache")
    with pytest.raises(RepoTooLarge):
        clone_repo(str(source), tmp_path / "cache", max_files=0)
    assert Path(original.local_path).exists()


@pytest.mark.parametrize("name", ["..", "../outside", "nested/child", "nested\\child"])
def test_cache_name_cannot_escape_parent(tmp_path: Path, name: str) -> None:
    source = _local_repo(tmp_path / "source", "VALUE = 1\n")
    with pytest.raises(ValueError):
        clone_repo(str(source), tmp_path / "cache", name=name)


def test_unverified_cache_is_not_reused(tmp_path: Path) -> None:
    source = _local_repo(tmp_path / "source", "VALUE = 1\n")
    _local_repo(tmp_path / "cache", "UNKNOWN = 1\n")
    with pytest.raises(FileExistsError):
        clone_repo(str(source), tmp_path / "cache", name="same")


def test_git_subprocess_has_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from reposleuth_toolkit.git_tool import _run_git

    def fake_run(args, **kwargs):
        assert kwargs.get("capture_output") is True
        assert kwargs.get("timeout", 0) > 0
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("reposleuth_toolkit.git_tool.subprocess.run", fake_run)
    _run_git(["--version"])


def test_git_timeout_raises_toolkit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from reposleuth_toolkit import RepoCloneError
    from reposleuth_toolkit.git_tool import _run_git

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 120)

    monkeypatch.setattr("reposleuth_toolkit.git_tool.subprocess.run", fake_run)
    with pytest.raises(RepoCloneError):
        _run_git(["clone", "offline", "destination"])


def test_local_copy_rejects_cache_inside_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _local_repo(tmp_path / "source", "VALUE = 1\n")

    def no_recursive_copy(*args, **kwargs):
        raise AssertionError("不能递归复制源目录到其子目录")

    monkeypatch.setattr("reposleuth_toolkit.git_tool.shutil.copytree", no_recursive_copy)
    with pytest.raises(ValueError):
        clone_repo(str(source), source / "cache")
