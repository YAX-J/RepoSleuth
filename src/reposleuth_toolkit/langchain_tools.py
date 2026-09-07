"""将 toolkit 无状态函数封装为 LangChain @tool —— 编排层的工具入口。

这个文件是 toolkit 与 Agent 世界之间唯一的"协议层"：
- 每个工具返回 Pydantic 模型的 JSON 字符串（对 LLM 友好、可校验）；
- 将来迁移为 MCP server 时，把这里的四个函数签名照搬成 tool schema 即可。
"""

from __future__ import annotations

from . import deps_tool, git_tool, ingest_tool, risk_tool

try:
    from langchain_core.tools import tool
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "langchain 工具封装需要 langchain-core：pip install 'reposleuth-toolkit[agent]'"
    ) from exc


@tool
def clone_repo_tool(url: str, dest_parent: str, max_size_mb: float = 50, max_files: int = 2000) -> str:
    """浅克隆 Git 仓库（GitHub URL 或本地路径），带克隆前后双重体积预检。返回 RepoInfo JSON；仓库超限时抛出 RepoTooLarge。"""
    return git_tool.clone_repo(
        url, dest_parent, max_size_mb=max_size_mb, max_files=max_files
    ).model_dump_json()


@tool
def repo_map_tool(repo_path: str) -> str:
    """静态分析 Python 仓库，产出模块节点、内部导入边与外部依赖（RepoMap JSON）。纯 AST 分析，不调用 LLM。"""
    return deps_tool.analyze_repo_map(repo_path).model_dump_json()


@tool
def risk_scan_tool(repo_path: str, engine: str = "builtin") -> str:
    """扫描代码风险：硬编码凭据、SQL 拼接、eval/exec、shell=True 等。engine 可选 builtin|semgrep|auto。返回 RiskReport JSON。"""
    return risk_tool.scan_risks(repo_path, engine=engine).model_dump_json()


@tool
def ingest_repo_tool(repo_path: str, max_total_chars: int = 200_000) -> str:
    """将仓库转为目录树 + 字符预算内的代码文本，供 LLM 阅读分析。返回 IngestResult JSON（含被预算截断的文件清单）。"""
    return ingest_tool.ingest_repo(repo_path, max_total_chars=max_total_chars).model_dump_json()


def get_langchain_tools() -> list:
    """编排层入口：返回全部工具实例，直接传给 create_react_agent / StateGraph。"""
    return [clone_repo_tool, repo_map_tool, risk_scan_tool, ingest_repo_tool]
