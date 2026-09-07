"""确定性节点：acquire（克隆）与 survey（测绘）。纯 toolkit 调用，零 LLM。"""

from __future__ import annotations

from pathlib import Path

from reposleuth_toolkit import analyze_repo_map, clone_repo, ingest_repo, scan_risks

from .state import CaseFile

DEFAULT_CACHE_DIR = Path("repos_cache")


def acquire_node(state: CaseFile, cache_dir: Path = DEFAULT_CACHE_DIR) -> dict:
    """克隆/获取仓库副本（toolkit 自带体积预检与本地目录回退）。"""
    info = clone_repo(state.repo_url, cache_dir)
    return {"repo": info}


def survey_node(state: CaseFile) -> dict:
    """测绘：依赖图 + 风险扫描 + 预算内文本化，全部确定性产物。"""
    path = state.repo.local_path
    return {
        "repo_map": analyze_repo_map(path, repo_name=state.repo.name),
        "risk_report": scan_risks(path),
        "ingest": ingest_repo(path),
    }
