"""RepoSleuth MCP Server：把 toolkit 的无状态工具暴露为 MCP（stdio）。

配置示例（.mcp.json / Claude / Cursor）：
{
  "mcpServers": {
    "reposleuth": {
      "command": "<python>",
      "args": ["-m", "reposleuth_mcp"],
      "env": {"PYTHONPATH": "<repo>/src", "GITHUB_TOKEN": "可选"}
    }
  }
}
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from reposleuth_toolkit import deps_tool, git_tool, github_search, ingest_tool, risk_tool

mcp = MCPServer("reposleuth")


@mcp.tool()
def github_search(query: str, max_results: int = 8) -> str:
    """Search GitHub repositories by keyword (rate-limit aware). Returns a JSON array of candidates."""
    try:
        return json.dumps(
            [c.model_dump() for c in github_search.search_repos(query, max_results=max_results)],
            ensure_ascii=False,
        )
    except github_search.GitHubSearchError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def clone_repo(url: str, dest_parent: str, max_size_mb: float = 50) -> str:
    """Shallow-clone a git repository (GitHub URL or local path) with size pre-checks.

    Returns RepoInfo JSON; returns an error object when the repo exceeds limits.
    """
    try:
        return git_tool.clone_repo(url, dest_parent, max_size_mb=max_size_mb).model_dump_json()
    except git_tool.RepoTooLarge as exc:
        return json.dumps({"error": "RepoTooLarge", "detail": str(exc)})


@mcp.tool()
def repo_map(repo_path: str) -> str:
    """Static analysis of a Python repo: module nodes, import edges, external deps. Returns RepoMap JSON. No LLM involved."""
    return deps_tool.analyze_repo_map(repo_path).model_dump_json()


@mcp.tool()
def risk_scan(repo_path: str, engine: str = "builtin") -> str:
    """Scan code risks: hardcoded credentials, SQL concat, eval/exec, shell=True. Returns RiskReport JSON."""
    return risk_tool.scan_risks(repo_path, engine=engine).model_dump_json()


@mcp.tool()
def ingest_repo_tool(repo_path: str, max_total_chars: int = 200000) -> str:
    """Convert a repo into a directory tree plus budget-capped code text for LLM reading. Returns IngestResult JSON."""
    return ingest_tool.ingest_repo(repo_path, max_total_chars=max_total_chars).model_dump_json()
