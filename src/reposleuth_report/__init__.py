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


def mermaid_from_repo_map(repo_map: RepoMap, max_nodes: int = 10, max_edges: int = 15) -> str:
    """从依赖图确定性生成 mermaid。

    选点策略（v2）：按"两端度数之和"给边打分，贪心保留得分最高的边——
    这样选出的节点天然成对连线，避免按度数选点导致节点孤立、图退化。
    """
    degree: dict[str, int] = {}
    for e in repo_map.edges:
        degree[e.source] = degree.get(e.source, 0) + 1
        degree[e.target] = degree.get(e.target, 0) + 1

    scored = sorted(
        (e for e in repo_map.edges if e.source != e.target),
        key=lambda e: (-(degree[e.source] + degree[e.target]), e.source, e.target),
    )

    chosen: set[str] = set()
    kept_edges = []
    for e in scored:
        new = (e.source not in chosen) + (e.target not in chosen)
        if len(chosen) + new > max_nodes:
            continue
        chosen.update((e.source, e.target))
        kept_edges.append(e)
        if len(chosen) >= max_nodes:
            # 节点满员后，仍收录已选节点之间的其余高分边（不超过 max_edges）
            for extra in scored:
                if len(kept_edges) >= max_edges:
                    break
                if extra.source in chosen and extra.target in chosen and extra not in kept_edges:
                    kept_edges.append(extra)
            break

    order = sorted(chosen, key=lambda m: (-degree[m], m))
    ids = {m: f"m{i}" for i, m in enumerate(order)}

    lines = ["graph TD"]
    for m in order:
        lines.append(f'{ids[m]}["{m}"]')
    for e in kept_edges:
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
