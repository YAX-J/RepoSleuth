"""feat/cockpit 冒烟测试：不启动服务器、不调真实 LLM。"""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from reposleuth_report import mermaid_from_repo_map
from reposleuth_web import build_demo, mermaid_html
from reposleuth_web.app import run_analysis, run_scout


def test_mermaid_html_escapes_and_wraps():
    html = mermaid_html('graph TD\nm0["a<b>"]')
    assert '<div class="mermaid">' in html
    assert "a&lt;b&gt;" in html  # XSS 转义
    assert "cdn.jsdelivr.net/npm/mermaid" in html


def test_build_demo_returns_blocks():
    demo = build_demo()
    assert demo is not None


def test_run_analysis_with_fake_llm(tmp_path, monkeypatch):
    """用 fake LLM 跑 run_analysis，验证 UI 数据流（markdown + mermaid HTML）。"""
    from reposleuth_web import app as app_mod

    def verdict(agent):
        return AIMessage(content=json.dumps({"agent": agent, "score": 7, "findings": [], "notes": "ok"}))

    report = json.dumps({"repo_name": "sample", "onboarding": ["读代码"], "risks": [], "scores": {}})
    msgs = [verdict("cartographer"), verdict("reader"), verdict("auditor"), AIMessage(content=report)]
    fake = GenericFakeChatModel(messages=iter(msgs))
    monkeypatch.setattr(app_mod, "_build_llm", lambda model: fake)

    # 本地样例仓库
    root = tmp_path / "sample"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "main.py").write_text("import requests\n", encoding="utf-8")

    md, mm = run_analysis(str(root), "glm-4-flash")
    assert "RepoSleuth 报告" in md
    assert 'class="mermaid"' in mm
    assert "graph TD" in mm
