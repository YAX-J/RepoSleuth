"""RepoSleuth Cockpit：Gradio 界面（模糊需求 / 直连分析 双模式）。"""

from __future__ import annotations

import html as _html
import os

import gradio as gr

from reposleuth_orchestrator import build_graph, build_scout_graph
from reposleuth_orchestrator.cli import _build_llm
from reposleuth_orchestrator.scout import DEFAULT_THRESHOLD
from reposleuth_orchestrator.state import CaseFile
from reposleuth_report import render_markdown


def mermaid_html(mermaid: str) -> str:
    """把 mermaid 文本包成自渲染 HTML（CDN 加载 mermaid.js）。"""
    body = _html.escape(mermaid or "")
    return (
        '<div class="mermaid">' + body + "</div>"
        '<script type="module">'
        'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";'
        "mermaid.initialize({startOnLoad:true});"
        "</script>"
    )


def _as_case(result) -> CaseFile:
    return result if isinstance(result, CaseFile) else CaseFile.model_validate(result)


def run_analysis(repo_url: str, model: str):
    """直连分析：仓库 URL → 报告。"""
    llm = _build_llm(model)
    final = build_graph(llm).invoke(CaseFile(repo_url=repo_url))
    case = _as_case(final)
    return render_markdown(case), mermaid_html(case.report.mermaid if case.report else "")


def run_scout(requirement: str, model: str, threshold: float):
    """侦察：模糊需求 → 候选列表（供确认）。返回 (候选行, radio 更新, 案卷状态)。"""
    llm = _build_llm(model)
    result = build_scout_graph(llm).invoke(CaseFile(requirement=requirement))
    case = _as_case(result)
    if not case.candidates or not case.ranked:
        return [], gr.update(choices=[], value=None), None, "未找到候选仓库，换个说法试试。"

    top = case.ranked[0]
    rows = [
        [c.full_name, c.stars, r.relevance, r.reason, c.description[:60]]
        for r, c in ((r, case.candidates[r.index]) for r in case.ranked[:5])
    ]
    note = (
        f"Top1 置信度 {top.relevance}/10 ≥ 阈值 {int(threshold)}，可直接点【分析选中仓库】；"
        if top.relevance >= threshold
        else f"置信度不足（Top1 {top.relevance}/10 < {int(threshold)}），请人工选择："
    )
    choices = [case.candidates[r.index].full_name for r in case.ranked[:3]]
    return rows, gr.update(choices=choices, value=choices[0]), case, note


def analyze_selected(selected: str | None, case: CaseFile | None, model: str):
    """确认候选后执行完整分析。"""
    if not case or not selected:
        return "请先搜索并选择候选仓库。", ""
    cand = next((c for c in case.candidates if c.full_name == selected), None)
    if cand is None:
        return "候选状态已失效，请重新搜索。", ""
    return run_analysis(cand.html_url, model)


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="RepoSleuth 代码侦探") as demo:
        gr.Markdown("# RepoSleuth 代码侦探\n说个大概，替你读透。")
        model = gr.Textbox(label="模型", value=os.environ.get("REPOSLEUTH_MODEL", "glm-4-flash"))
        report = gr.Markdown(label="分析报告")
        mermaid_view = gr.HTML()

        with gr.Tab("模糊需求（scouting）"):
            req = gr.Textbox(label="需求描述", placeholder="例：找一个处理 PDF 的轻量 Python 库")
            threshold = gr.Slider(0, 10, value=DEFAULT_THRESHOLD, step=1, label="置信度阈值")
            scout_btn = gr.Button("搜索候选仓库")
            cand_table = gr.Dataframe(
                headers=["仓库", "stars", "相关度", "理由", "简介"], interactive=False
            )
            gate_note = gr.Markdown()
            chosen = gr.Radio(label="选择仓库", choices=[])
            cand_state = gr.State(None)
            analyze_btn = gr.Button("分析选中仓库")

            scout_btn.click(
                run_scout, [req, model, threshold],
                [cand_table, chosen, cand_state, gate_note],
            )
            analyze_btn.click(
                analyze_selected, [chosen, cand_state, model], [report, mermaid_view]
            )

        with gr.Tab("直连分析"):
            url_in = gr.Textbox(label="GitHub URL 或本地路径")
            direct_btn = gr.Button("分析")
            direct_btn.click(run_analysis, [url_in, model], [report, mermaid_view])

    return demo


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    build_demo().launch(server_name="127.0.0.1", server_port=int(os.environ.get("PORT", "7860")))
