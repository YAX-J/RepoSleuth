"""feat/mcp-release 验收测试：工具注册契约 + 经 call_tool 的真实执行。"""

from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture()
def sample_repo(tmp_path):
    root = tmp_path / "sample"
    app = root / "app"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "main.py").write_text("import requests\n", encoding="utf-8")
    (root / "settings.py").write_text('API_KEY = "sk-live-abcdefgh123456"\n', encoding="utf-8")
    return root


def _run(coro):
    return asyncio.run(coro)


def test_tools_registered():
    from reposleuth_mcp.server import mcp

    tools = _run(mcp.list_tools())
    assert {t.name for t in tools} == {
        "github_search", "clone_repo", "repo_map", "risk_scan", "ingest_repo_tool",
    }
    for t in tools:
        assert t.description  # 每个工具都有描述（LLM 可读契约）


def _text(result) -> str:
    return result.content[0].text


def test_call_repo_map_and_risk_scan(sample_repo):
    from reposleuth_mcp.server import mcp

    result = _run(mcp.call_tool("repo_map", {"repo_path": str(sample_repo)}))
    payload = json.loads(_text(result))
    module_paths = {m["path"] for m in payload["modules"]}
    assert "app.main" in module_paths
    assert "requests" in payload["external_deps"]

    result = _run(mcp.call_tool("risk_scan", {"repo_path": str(sample_repo)}))
    payload = json.loads(_text(result))
    assert any(f["rule_id"] == "RS001-SECRET" for f in payload["findings"])


def test_call_clone_repo_too_large(sample_repo, tmp_path, monkeypatch):
    """超限仓库返回错误 JSON 而非崩溃（MCP 工具不允许裸抛异常）。

    注：用 monkeypatch 固定 _measure 返回值，使测试不依赖真实磁盘测量时序。
    """
    import reposleuth_toolkit.git_tool as git_tool

    from reposleuth_mcp.server import mcp

    monkeypatch.setattr(git_tool, "_measure", lambda p: (9999, 10 ** 9))

    dest = tmp_path / "out"
    dest.mkdir()
    result = _run(mcp.call_tool(
        "clone_repo", {"url": str(sample_repo), "dest_parent": str(dest), "max_files": 1}
    ))
    payload = json.loads(_text(result))
    assert payload["error"] == "RepoTooLarge"


def test_reuse_branch_also_checks_limits(tmp_path, monkeypatch):
    """回归：复用已存在目录时同样执行阈值检查（曾绕过预检的 bug）。"""
    import reposleuth_toolkit.git_tool as git_tool

    dest = tmp_path / "sample"
    dest.mkdir()
    (dest / "a.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(git_tool, "_measure", lambda p: (9999, 10 ** 9))

    with pytest.raises(git_tool.RepoTooLarge):
        git_tool.clone_repo(str(dest), tmp_path / "out", name="sample", max_files=1)
