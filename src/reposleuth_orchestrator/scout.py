"""侦察阶段：需求理解 → 多路检索 → 重排 → 置信度门控。

分层：LLM 节点（需求理解/重排）在此层，GitHub 检索是无状态工具（toolkit）。
门控策略（方案二）：Top1 relevance >= 阈值 → 自动直选；否则返回候选列表由用户确认。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from reposleuth_toolkit import RepoCandidate, search_repos

from .state import CaseFile, RankedCandidate

_PROMPT_DIR = Path(__file__).parent / "prompts"
DEFAULT_THRESHOLD = 7


class QueryPlan(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=5)


class Ranking(BaseModel):
    ranked: list[RankedCandidate] = Field(max_length=20)


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def make_query_agent(llm):
    """需求 → 搜索词组（LLM 结构化输出，复用 agents 的解析容错）。"""
    from .agents import _structured

    template = _load_prompt("scout_query")

    def node(state: CaseFile) -> dict:
        plan = _structured(llm, template.replace("<<<REQUIREMENT>>>", state.requirement), QueryPlan)
        return {"queries": plan.queries}

    return node


def make_search_node(search_fn=search_repos, per_query: int = 5):
    """多路检索 + 去重合并（确定性）。search_fn 可注入以便测试。"""

    def node(state: CaseFile) -> dict:
        merged: dict[str, RepoCandidate] = {}
        for query in state.queries:
            try:
                for cand in search_fn(query, max_results=per_query):
                    merged.setdefault(cand.full_name, cand)
            except Exception as exc:  # 单路失败不拖垮整体
                print(f"[scout] 查询 {query!r} 失败: {exc}", file=sys.stderr)
        return {"candidates": list(merged.values())}

    return node


def make_rank_agent(llm):
    """候选重排打分。"""
    from .agents import _structured

    template = _load_prompt("scout_rank")

    def node(state: CaseFile) -> dict:
        items = [
            {"index": i, "full_name": c.full_name, "description": c.description[:120],
             "stars": c.stars, "language": c.language}
            for i, c in enumerate(state.candidates)
        ]
        prompt = template.replace("<<<REQUIREMENT>>>", state.requirement)
        prompt = prompt.replace("<<<CANDIDATES>>>", json.dumps(items, ensure_ascii=False))
        ranking = _structured(llm, prompt, Ranking)
        # 只保留能对回原始候选的记录，按相关度排序
        ranked = sorted(
            (r for r in ranking.ranked if 0 <= r.index < len(state.candidates)),
            key=lambda r: -r.relevance,
        )
        return {"ranked": ranked}

    return node


def gate(ranked: list[RankedCandidate], threshold: int = DEFAULT_THRESHOLD) -> tuple[str | None, list[RankedCandidate]]:
    """置信度门控（方案二）。

    返回 (auto_selected_url | None, shortlist)：
    - Top1 relevance >= 阈值 → shortlist 即完整排序，调用方取 Top1 直选；
    - 否则 shortlist 为前 3 个候选，交由用户确认。
    两种情况都返回 None 作为 auto 位，由调用方结合 shortlist[0].relevance 判断。
    """
    if not ranked:
        return None, []
    if ranked[0].relevance >= threshold:
        return None, ranked
    return None, ranked[:3]


def resolve_url(ranked: list[RankedCandidate], candidates: list[RepoCandidate]) -> str | None:
    """取 shortlist Top1 对应的仓库 URL。"""
    if not ranked:
        return None
    by_index = {i: c for i, c in enumerate(candidates)}
    cand = by_index.get(ranked[0].index)
    return cand.html_url if cand else None
