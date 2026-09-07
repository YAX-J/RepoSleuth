"""RepoSleuth 报告渲染层：mermaid 生成 + Markdown 渲染。

纯确定性逻辑，不依赖 LLM；输入是编排层产出的 CaseFile / RepoMap。
遵循 AGENTS.md"确定性优先"：架构图由依赖图数据直接渲染，不让 LLM 编。
"""

from __future__ import annotations

from pathlib import Path

from reposleuth_orchestrator.state import CaseFile
from reposleuth_toolkit.models import RepoMap

SCORE_LABELS = {
    "cartographer": "架构（Cartographer）",
    "reader": "可读性（Reader）",
    "auditor": "安全（Auditor）",
}


def mermaid_from_repo_map(repo_map: RepoMap, max_nodes: int = 10) -> str:
    """从依赖图确定性生成 mermaid：取关联度最高的 N 个模块及其内部边。"""
    degree: dict[str, int] = {}
    for e in repo_map.edges:
        degree[e.source] = degree.get(e.source, 0) + 1
        degree[e.target] = degree.get(e.target, 0) + 1
    top = sorted(degree, key=lambda m: (-degree[m], m))[:max_nodes]
    chosen = set(top)
    ids = {m: f"m{i}" for i, m in enumerate(top)}

    lines = ["graph TD"]
    for m in top:
        lines.append(f'{ids[m]}["{m}"]')
    for e in repo_map.edges:
        if e.source in chosen and e.target in chosen:
            lines.append(f"{ids[e.source]} --> {ids[e.target]}")
    return "\n".join(lines)


def render_markdown(case: CaseFile) -> str:
    """渲染最终报告 Markdown；未走完流水线（缺 report）时抛 ValueError。"""
    report = case.report
    if report is None:
        raise ValueError("案卷中缺少 report，请先跑完编排流水线")

    # 分数优先用编排层回填值；缺失时从三侦探结论兜底
    scores = report.scores or {
        v.agent: v.score
        for v in (case.verdict_cartographer, case.verdict_reader, case.verdict_auditor)
        if v is not None
    }

    lines: list[str] = [f"# RepoSleuth 报告 · {report.repo_name}", ""]

    lines += ["## 综合评分", ""]
    for agent, label in SCORE_LABELS.items():
        if agent in scores:
            lines.append(f"- {label}：**{scores[agent]}/10**")
    lines.append("")

    lines += ["## 架构图", "", "```mermaid", report.mermaid, "```", ""]

    lines += ["## 新人上手路线", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(report.onboarding, 1)]
    lines.append("")

    lines += ["## 风险清单", ""]
    if report.risks:
        lines += [f"- [ ] {risk}" for risk in report.risks]
    else:
        lines.append("- 未发现风险")

    if case.repo_map is not None:
        stats = case.repo_map.stats
        lines += [
            "",
            "## 附录 · 仓库画像",
            "",
            f"- 模块数：{stats.get('modules', '-')}；内部依赖边：{stats.get('internal_edges', '-')}；"
            f"外部依赖：{stats.get('external_deps', '-')}；总行数：{stats.get('total_loc', '-')}",
        ]

    return "\n".join(lines) + "\n"


def save_report(case: CaseFile, out_dir: Path) -> Path:
    """渲染并写入 out_dir/report_<repo>.md，返回文件路径。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = case.report.repo_name if case.report else "unknown"
    path = out_dir / f"report_{name}.md"
    path.write_text(render_markdown(case), encoding="utf-8")
    return path
