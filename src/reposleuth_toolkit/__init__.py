"""RepoSleuth 工具封装层：无状态、确定性、不依赖 LLM。"""

from .models import (
    CallEdge,
    IngestResult,
    Language,
    ModuleNode,
    RepoCandidate,
    RepoInfo,
    RepoMap,
    RiskFinding,
    RiskReport,
    Severity,
)
from .git_tool import RepoTooLarge, clone_repo, detect_language
from .deps_tool import analyze_repo_map
from .risk_tool import scan_risks
from .ingest_tool import ingest_repo
from .github_search import GitHubSearchError, search_repos

__version__ = "0.1.0"

__all__ = [
    "CallEdge", "IngestResult", "Language", "ModuleNode", "RepoCandidate", "RepoInfo",
    "RepoMap", "RiskFinding", "RiskReport", "Severity",
    "RepoTooLarge", "clone_repo", "detect_language",
    "analyze_repo_map", "scan_risks", "ingest_repo",
    "GitHubSearchError", "search_repos",
]
