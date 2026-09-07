"""GitHub 仓库搜索：Search API 封装（限流退避 + 候选模型化）。

纯状态工具，不依赖 LLM；token 可选（GITHUB_TOKEN 提升限额到 30 次/分钟）。
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from .models import RepoCandidate

SEARCH_URL = "https://api.github.com/search/repositories"
# 未认证 10 次/分钟 → 单次调用间隔 ≥ 6.5s
MIN_INTERVAL = 6.5
_last_call = 0.0


class GitHubSearchError(RuntimeError):
    """搜索失败（限流/网络/配额）。"""


def _get(url: str, token: str | None) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise GitHubSearchError("GitHub Search 限流，请稍后重试或配置 GITHUB_TOKEN") from exc
        raise GitHubSearchError(f"GitHub API HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GitHubSearchError(f"网络错误: {exc.reason}") from exc


def search_repos(query: str, max_results: int = 8, token: str | None = None) -> list[RepoCandidate]:
    """按 query 搜索仓库，返回 RepoCandidate 列表（按 star 排序）。"""
    global _last_call
    token = token or os.environ.get("GITHUB_TOKEN") or None

    wait = MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()

    q = urllib.parse.quote(query)
    data = _get(f"{SEARCH_URL}?q={q}&per_page={max_results}&sort=stars", token)
    items = data.get("items", [])
    return [
        RepoCandidate(
            full_name=item["full_name"],
            html_url=item["html_url"],
            description=item.get("description") or "",
            stars=item.get("stargazers_count", 0),
            language=item.get("language") or "",
            size_kb=item.get("size", 0),
        )
        for item in items
    ]
