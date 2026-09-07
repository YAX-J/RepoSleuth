"""report 渲染层测试：确定性，无 LLM / 无网络。"""

from __future__ import annotations

import pytest

from reposleuth_orchestrator.state import CaseFile, DetectiveVerdict, FinalReport
from reposleuth_report import render_markdown, save_report


def _case() -> CaseFile:
    return CaseFile(
        repo_url="https://example.com/x/sample",
        verdict_cartographer=DetectiveVerdict(agent="cartographer", score=7),
        verdict_reader=DetectiveVerdict(agent="reader", score=6),
        verdict_auditor=DetectiveVerdict(agent="auditor", score=8),
        report=FinalReport(
            repo_name="sample",
            mermaid="graph TD; app_main --> app_utils",
            onboarding=["读 app/main.py", "跑测试"],
            risks=["硬编码凭据", "eval 使用"],
            scores={},
        ),
    )


def test_render_markdown_contains_all_sections():
    md = render_markdown(_case())
    assert "# RepoSleuth 报告 · sample" in md
    assert "- 架构（Cartographer）：**7/10**" in md
    assert "```mermaid" in md and "graph TD; app_main --> app_utils" in md
    assert "1. 读 app/main.py" in md
    assert "- [ ] 硬编码凭据" in md and "- [ ] eval 使用" in md


def test_render_requires_report():
    with pytest.raises(ValueError):
        render_markdown(CaseFile(repo_url="x"))


def test_save_report_writes_file(tmp_path):
    path = save_report(_case(), tmp_path)
    assert path.name == "report_sample.md"
    assert "mermaid" in path.read_text(encoding="utf-8")
