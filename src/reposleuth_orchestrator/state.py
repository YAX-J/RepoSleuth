"""编排层状态契约：CaseFile 是贯穿整条流水线的"案卷"。

设计要点：
- 三侦探并行写各自独立字段（verdict_*），避免并行节点写同一键互相覆盖；
- toolkit 产物（RepoInfo/RepoMap/RiskReport/IngestResult）直接复用，不重复建模；
- 置信度门控（feat/scouting）后续在此扩展，本分支只做直连模式。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from reposleuth_toolkit.models import IngestResult, RepoInfo, RepoMap, RiskReport


class DetectiveVerdict(BaseModel):
    """单个侦探 Agent 的结构化结论。"""

    agent: str = Field(description="cartographer / reader / auditor")
    score: int = Field(ge=0, le=10, description="该视角评分")
    findings: list[str] = Field(default_factory=list, description="关键发现")
    notes: str = Field(default="", description="一句话总评")


class FinalReport(BaseModel):
    """主笔 Agent 汇总产物（报告三件套）。"""

    repo_name: str
    mermaid: str = Field(default="", description="mermaid 架构图，由编排层从依赖图确定性渲染，不由 LLM 编造")
    onboarding: list[str] = Field(default_factory=list, description="新人上手路线，<=5 步")
    risks: list[str] = Field(default_factory=list, description="风险清单，<=6 条")
    scores: dict[str, int] = Field(default_factory=dict, description="各侦探评分，由编排层回填")


class CaseFile(BaseModel):
    """整条流水线的共享状态。"""

    repo_url: str = Field(description="仓库 URL 或本地路径（直连模式）")
    requirement: str = Field(default="", description="用户模糊需求（scouting 分支启用）")

    # --- toolkit 确定性产物 ---
    repo: RepoInfo | None = None
    repo_map: RepoMap | None = None
    risk_report: RiskReport | None = None
    ingest: IngestResult | None = None

    # --- 三侦探并行结论（各写各的字段） ---
    verdict_cartographer: DetectiveVerdict | None = None
    verdict_reader: DetectiveVerdict | None = None
    verdict_auditor: DetectiveVerdict | None = None

    # --- 主笔汇总 ---
    report: FinalReport | None = None
