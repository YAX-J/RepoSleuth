"""feat/scouting 冒烟测试：注入 stub 搜索函数 + fake LLM，不依赖网络。

覆盖：
- 需求理解 → 多路检索去重 → 重排打分全链路；
- 置信度门控：高分自动直选 / 低分进入候选确认；
- 单路检索失败不拖垮整体。
"""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from reposleuth_toolkit import RepoCandidate

from reposleuth_orchestrator import build_scout_graph
from reposleuth_orchestrator.scout import gate, resolve_url


def _candidate(i: int, name: str, desc: str, stars: int) -> RepoCandidate:
    return RepoCandidate(full_name=name, html_url=f"https://github.com/{name}",
                         description=desc, stars=stars, language="Python", size_kb=100)


CANDIDATES = [
    _candidate(0, "pdfme/pdfme", "Lightweight PDF parser and writer", 1200),
    _candidate(1, "other/unrelated", "A game engine in Python", 900),
    _candidate(2, "pypdf/pypdf", "PDF processing library", 8000),
]


def _stub_search():
    def search_fn(query, max_results=5):
        return list(CANDIDATES)
    return search_fn


def _scripted_llm(responses: list[str]):
    return GenericFakeChatModel(messages=iter(AIMessage(content=r) for r in responses))


def _queries_json() -> str:
    return json.dumps({"queries": ["pdf python", "topic:pdf"]})


def _ranking_json(scores: list[int]) -> str:
    return json.dumps({
        "ranked": [{"index": i, "relevance": s, "reason": "匹配"} for i, s in enumerate(scores)]
    })


def test_scout_high_confidence_auto_select(tmp_path):
    """Top1 relevance >= 阈值 → 自动直选。"""
    llm = _scripted_llm([_queries_json(), _ranking_json([9, 2, 8])])
    case = build_scout_graph(llm, search_fn=_stub_search()).invoke(
        {"requirement": "找个处理 PDF 的轻量库"}
    )
    assert case["queries"] == ["pdf python", "topic:pdf"]
    assert len(case["candidates"]) == 3          # 去重后 3 个
    assert case["ranked"][0].relevance == 9

    url, shortlist = gate(case["ranked"])
    assert url is None                            # URL 由 resolve_url 解析
    assert resolve_url(shortlist, case["candidates"]) == "https://github.com/pdfme/pdfme"


def test_scout_low_confidence_needs_confirmation():
    """Top1 relevance < 阈值 → 返回前 3 候选等用户确认。"""
    llm = _scripted_llm([_queries_json(), _ranking_json([4, 6, 5])])
    case = build_scout_graph(llm, search_fn=_stub_search()).invoke(
        {"requirement": "模糊需求"}
    )
    url, shortlist = gate(case["ranked"], threshold=7)
    assert url is None
    assert len(shortlist) == 3
    assert resolve_url(shortlist, case["candidates"]) == "https://github.com/other/unrelated"


def test_scout_survives_partial_search_failure():
    """一路查询失败，另一路仍有结果（去重合并不崩溃）。"""
    calls = {"n": 0}

    def flaky_search(query, max_results=5):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("rate limited")
        return [CANDIDATES[0]]

    llm = _scripted_llm([_queries_json(), _ranking_json([7])])
    case = build_scout_graph(llm, search_fn=flaky_search).invoke({"requirement": "pdf 库"})
    assert len(case["candidates"]) == 1
    assert case["ranked"][0].relevance == 7
