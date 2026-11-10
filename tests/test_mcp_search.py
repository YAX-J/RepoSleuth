"""仓库分析基础能力的离线回归测试。"""

from __future__ import annotations

import asyncio
import json

import pytest


@pytest.mark.parametrize("fail", [False, True])
def test_mcp_github_search_executes_toolkit(monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    import reposleuth_toolkit.github_search as search_module
    from reposleuth_mcp.server import mcp
    from reposleuth_toolkit.models import RepoCandidate

    def fake_search(query: str, max_results: int):
        assert (query, max_results) == ("offline query", 3)
        if fail:
            raise search_module.GitHubSearchError("synthetic rate limit")
        return [RepoCandidate(full_name="demo/repo", html_url="https://github.com/demo/repo")]

    monkeypatch.setattr(search_module, "search_repos", fake_search)
    result = asyncio.run(mcp.call_tool("github_search", {"query": "offline query", "max_results": 3}))
    payload = json.loads(result.content[0].text)
    if fail:
        assert payload == {"error": "synthetic rate limit"}
    else:
        assert payload[0]["full_name"] == "demo/repo"
