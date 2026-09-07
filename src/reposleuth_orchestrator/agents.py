"""侦探 Agent 节点工厂：prompt 加载 + JSON 解析 + pydantic 校验。

设计要点：
- llm 由 build_graph 注入（便于用 fake model 冒烟、便于换模型）；
- 结构化输出走"LLM 出 JSON 文本 → 提取 → model_validate"的手工路径，
  不依赖厂商 function-calling 特性，任何 BaseChatModel 都能跑；
- 分数以 LLM 给出为准，但 FinalReport.scores 由编排层回填，主笔不得编造。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from .state import CaseFile, DetectiveVerdict, FinalReport

PROMPT_DIR = Path(__file__).parent / "prompts"
EVIDENCE_CHAR_BUDGET = 20_000


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def _evidence(state: CaseFile) -> str:
    """把 toolkit 确定性产物拼装成证据包（确定性逻辑，预算内截断）。"""
    parts: list[str] = []
    if state.repo_map is not None:
        parts.append("## 依赖图（模块节点 + 导入边）\n" + state.repo_map.model_dump_json())
    if state.risk_report is not None:
        parts.append("## 风险扫描结果\n" + state.risk_report.model_dump_json())
    if state.ingest is not None:
        text = state.ingest.tree_text + "\n" + state.ingest.content_text
        parts.append("## 仓库文本（预算内）\n" + text[:EVIDENCE_CHAR_BUDGET])
    return "\n\n".join(parts)


def _extract_json(raw: str) -> str:
    """从 LLM 输出中提取首个 JSON 对象（容忍 markdown 代码围栏与前后缀文本）。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"LLM 输出中未找到 JSON 对象: {text[:200]!r}")
    return text[start : end + 1]


def _structured(llm, prompt: str, model: type[BaseModel]):
    """调用 LLM 并校验为 pydantic 模型；解析失败抛异常（编排层负责重试/降级）。"""
    raw = llm.invoke(prompt)
    content = raw.content if hasattr(raw, "content") else str(raw)
    if isinstance(content, list):  # 多模态内容块
        content = "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return model.model_validate(json.loads(_extract_json(content)))


def make_cartographer(llm):
    template = _load_prompt("cartographer")

    def node(state: CaseFile) -> dict:
        verdict = _structured(llm, template.replace("<<<EVIDENCE>>>", _evidence(state)), DetectiveVerdict)
        verdict.agent = "cartographer"
        return {"verdict_cartographer": verdict}

    return node


def make_reader(llm):
    template = _load_prompt("reader")

    def node(state: CaseFile) -> dict:
        verdict = _structured(llm, template.replace("<<<EVIDENCE>>>", _evidence(state)), DetectiveVerdict)
        verdict.agent = "reader"
        return {"verdict_reader": verdict}

    return node


def make_auditor(llm):
    template = _load_prompt("auditor")

    def node(state: CaseFile) -> dict:
        verdict = _structured(llm, template.replace("<<<EVIDENCE>>>", _evidence(state)), DetectiveVerdict)
        verdict.agent = "auditor"
        return {"verdict_auditor": verdict}

    return node


def make_chief(llm):
    template = _load_prompt("chief")

    def node(state: CaseFile) -> dict:
        verdicts = [
            v
            for v in (state.verdict_cartographer, state.verdict_reader, state.verdict_auditor)
            if v is not None
        ]
        evidence = template.replace("<<<VERDICTS>>>", json.dumps([v.model_dump() for v in verdicts], ensure_ascii=False))
        evidence = evidence.replace("<<<EVIDENCE>>>", _evidence(state))
        report = _structured(llm, evidence, FinalReport)
        report.scores = {v.agent: v.score for v in verdicts}  # 编排层回填，LLM 不得编造
        return {"report": report}

    return node
