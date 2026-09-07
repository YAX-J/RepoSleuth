"""Web Server 契约冒烟测试：不依赖真实 LLM / 网络。

用 FakeGraph 模拟 LangGraph stream 的 updates 流，断言 SSE 事件序列符合
前后端协议：stage/queries/candidates/ranked/gate 与 acquire/survey/verdict/report。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import reposleuth_web.server as srv
from reposleuth_orchestrator.state import DetectiveVerdict, FinalReport, RankedCandidate
from reposleuth_toolkit.models import (
    CallEdge,
    ModuleNode,
    RepoCandidate,
    RepoInfo,
    RepoMap,
    RiskFinding,
    RiskReport,
    Severity,
)


class FakeGraph:
    """按预设 updates 序列回放的假状态机。"""

    def __init__(self, updates: list[dict]):
        self._updates = updates

    def stream(self, _state, stream_mode="updates"):
        yield from self._updates


def _sse_events(resp) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]


_CAND = RepoCandidate(
    full_name="pallets/click", html_url="https://github.com/pallets/click",
    description="CLI toolkit", stars=15000, language="Python", size_kb=5000,
)


def test_scout_auto_gate(client_factory, monkeypatch):
    client = client_factory(scout_updates=[
        {"plan": {"queries": ["python cli"]}},
        {"search": {"candidates": [_CAND]}},
        {"rank": {"ranked": [RankedCandidate(index=0, relevance=9, reason="fit")]}},
    ])
    resp = client.post("/api/scout", json={"requirement": "一个好用的 Python CLI 框架"})
    assert resp.status_code == 200
    types = [e["type"] for e in _sse_events(resp)]
    assert types[0] == "stage"
    assert "queries" in types and "candidates" in types and "ranked" in types
    gate = next(e for e in _sse_events(resp) if e["type"] == "gate")
    assert gate["mode"] == "auto"
    assert gate["repo_url"] == "https://github.com/pallets/click"
    assert types[-1] == "done"


def test_scout_confirm_gate(client_factory):
    client = client_factory(scout_updates=[
        {"plan": {"queries": ["q"]}},
        {"search": {"candidates": [_CAND]}},
        {"rank": {"ranked": [RankedCandidate(index=0, relevance=4, reason="meh")]}},
    ])
    resp = client.post("/api/scout", json={"requirement": "模糊需求xy"})
    gate = next(e for e in _sse_events(resp) if e["type"] == "gate")
    assert gate["mode"] == "confirm"
    assert gate["shortlist"][0]["full_name"] == "pallets/click"


def test_investigate_full_pipeline(client_factory):
    client = client_factory(inv_updates=[
        {"acquire": {"repo": RepoInfo(
            name="click", url="https://github.com/pallets/click",
            local_path="repos_cache/click", file_count=100, total_size_bytes=2_000_000)}},
        {"survey": {
            "repo_map": RepoMap(repo_name="click", modules=[ModuleNode(name="cli", path="cli")],
                                edges=[CallEdge(source="cli", target="core")],
                                stats={"modules": 90, "internal_edges": 196,
                                       "external_deps": 7, "total_loc": 29121}),
            "risk_report": RiskReport(repo_name="click", findings=[
                RiskFinding(rule_id="hardcoded-secret", severity=Severity.high,
                            path="tests/x.py", line=1, message="secret")])}},
        {"cartographer": {"verdict_cartographer": DetectiveVerdict(agent="cartographer", score=8, findings=["f1"], notes="ok")}},
        {"reader": {"verdict_reader": DetectiveVerdict(agent="reader", score=8, findings=["f2"], notes="ok")}},
        {"auditor": {"verdict_auditor": DetectiveVerdict(agent="auditor", score=8, findings=["f3"], notes="ok")}},
        {"chief": {"report": FinalReport(
            repo_name="click", mermaid="graph TD\n  m0[cli]", onboarding=["step1"],
            risks=["r1"], scores={"cartographer": 8, "reader": 8, "auditor": 8})}},
    ])
    resp = client.post("/api/investigate", json={"repo_url": "https://github.com/pallets/click"})
    events = _sse_events(resp)
    types = [e["type"] for e in events]
    assert types == ["acquire", "survey", "verdict", "verdict", "verdict", "report", "done"]
    report = next(e for e in events if e["type"] == "report")["report"]
    assert report["repo_name"] == "click"
    assert report["scores"]["cartographer"] == 8
    assert "graph TD" in report["mermaid"]
    assert "## 架构图" in report["markdown"]  # render_markdown 正常产出


def test_scout_requires_model(client_factory_without_model):
    client = client_factory_without_model
    resp = client.post("/api/scout", json={"requirement": "模糊需求xy"})
    events = _sse_events(resp)
    assert events[0]["type"] == "error"
    assert "REPOSLEUTH_MODEL" in events[0]["message"]


@pytest.fixture
def client_factory(monkeypatch):
    def _make(scout_updates=None, inv_updates=None):
        monkeypatch.setattr(srv, "_build_llm", lambda model: object())
        if scout_updates is not None:
            monkeypatch.setattr(srv, "build_scout_graph", lambda llm: FakeGraph(scout_updates))
        if inv_updates is not None:
            monkeypatch.setattr(srv, "build_graph", lambda llm, cache_dir=None: FakeGraph(inv_updates))
        return TestClient(srv.app)
    return _make


@pytest.fixture
def client_factory_without_model(monkeypatch):
    monkeypatch.setattr(srv, "_default_model", lambda: "")
    return TestClient(srv.app)
