"""固定版本 golden 仓库的离线回归；未准备对应本地副本时明确跳过。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from reposleuth_toolkit import analyze_repo_map

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BASELINES = json.loads(
    (_PROJECT_ROOT / "tests" / "golden_repos" / "baselines.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("full_name", ["pallets/click", "httpie/cli"])
def test_golden_static_analysis(full_name: str) -> None:
    """模块、边、外部依赖与行数匹配基线，所有边均连接真实模块。"""
    cache_root = Path(os.environ.get("REPOSLEUTH_GOLDEN_ROOT", str(_PROJECT_ROOT / "repos_cache")))
    repo_path = cache_root / full_name.split("/")[-1]
    expected = _BASELINES[full_name]
    if not (repo_path / ".git").exists():
        pytest.skip(f"未准备离线 golden 仓库：{repo_path}")
    revision = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip()
    if revision != expected["revision"]:
        pytest.skip(f"{full_name} 需要固定版本 {expected['revision']}，当前为 {revision}")
    result = analyze_repo_map(repo_path)
    for metric in ("modules", "internal_edges", "external_deps", "total_loc"):
        assert result.stats[metric] == expected[metric], f"{full_name}: {metric}"
    modules = {m.path for m in result.modules}
    assert all(e.source in modules and e.target in modules for e in result.edges)
