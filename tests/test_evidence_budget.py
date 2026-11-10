"""仓库分析基础能力的离线回归测试。"""

from __future__ import annotations



def test_evidence_budget_covers_map_risks_and_code() -> None:
    from reposleuth_orchestrator.agents import EVIDENCE_CHAR_BUDGET, _evidence
    from reposleuth_orchestrator.state import CaseFile
    from reposleuth_toolkit.models import IngestResult, ModuleNode, RepoMap, RiskFinding, RiskReport, Severity

    case = CaseFile(
        repo_map=RepoMap(repo_name="demo", modules=[
            ModuleNode(name=f"m{i}", path=f"demo.module_{i}") for i in range(2000)
        ]),
        risk_report=RiskReport(repo_name="demo", findings=[
            RiskFinding(rule_id="synthetic", severity=Severity.high, path="app.py", line=i, message="risk")
            for i in range(1000)
        ]),
        ingest=IngestResult(repo_name="demo", tree_text="demo/", content_text="CODE_SENTINEL\n" * 5000),
    )
    evidence = _evidence(case)
    assert len(evidence) <= EVIDENCE_CHAR_BUDGET
    assert "依赖图" in evidence and "风险扫描结果" in evidence and "CODE_SENTINEL" in evidence
