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

from reposleuth_toolkit.evidence_tool import resolve_citations
from reposleuth_toolkit.models import CitationRequest, EvidencePacket, SourceExcerpt

from .state import CaseFile, DetectiveVerdict, FinalReport

PROMPT_DIR = Path(__file__).parent / "prompts"
EVIDENCE_CHAR_BUDGET = 20_000


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def _source_block(source: SourceExcerpt) -> str:
    return f"\n[{source.id}] {source.path}:{source.start_line}-{source.end_line}\n{source.snippet}\n"


def _evidence_packet(state: CaseFile, char_budget: int = EVIDENCE_CHAR_BUDGET) -> EvidencePacket:
    """限制证据总预算；可引用白名单仅包含本轮完整展示的工具层片段。"""
    if char_budget < 0:
        raise ValueError("证据预算不能为负数")
    parts: list[str] = []
    if state.repo_map is not None:
        parts.append("## 依赖图（模块节点 + 导入边）\n" + state.repo_map.model_dump_json())
    if state.risk_report is not None:
        parts.append("## 风险扫描结果\n" + state.risk_report.model_dump_json())
    if state.ingest is not None:
        content = ("".join(_source_block(s) for s in state.ingest.sources)
                   if state.ingest.sources else state.ingest.content_text)
        text = state.ingest.tree_text[:600] + "\n" + content
        parts.append("## 仓库文本（预算内）\n" + text)
    if not parts:
        return EvidencePacket()
    # 为每类证据保留份额，避免较大的依赖图挤掉风险与代码；总预算包含分隔符。
    available = max(0, char_budget - 2 * (len(parts) - 1))
    share = available // len(parts)
    allocations = [min(len(part), share) for part in parts]
    spare = available - sum(allocations)
    for i in reversed(range(len(parts))):
        extra = min(spare, len(parts[i]) - allocations[i])
        allocations[i] += extra
        spare -= extra
    marker = "\n...[证据过长已截断]"
    bounded = []
    visible: list[SourceExcerpt] = []
    for i, (part, limit) in enumerate(zip(parts, allocations)):
        if i == len(parts) - 1 and state.ingest is not None and state.ingest.sources:
            part = ("## 仓库文本（预算内）\n" + state.ingest.tree_text[:min(600, limit // 4)] + "\n")[:limit]
            for source_index, source in enumerate(state.ingest.sources):
                block = _source_block(source)
                reserve = len(marker) if source_index < len(state.ingest.sources) - 1 else 0
                if len(part) + len(block) + reserve > limit:
                    break
                part += block
                visible.append(source)
            if len(visible) < len(state.ingest.sources):
                part += marker[:max(0, limit - len(part))]
            bounded.append(part)
            continue
        if len(part) > limit:
            suffix = marker[:limit]
            part = part[:limit - len(suffix)] + suffix
        bounded.append(part)
    return EvidencePacket(text="\n\n".join(bounded)[:char_budget], sources=visible)


def _evidence(state: CaseFile, char_budget: int = EVIDENCE_CHAR_BUDGET) -> str:
    """兼容只需要文本的调用方，引用校验使用完整 EvidencePacket。"""
    return _evidence_packet(state, char_budget).text


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


def _structured(llm, prompt: str, model: type[BaseModel], retries: int = 2):
    """调用 LLM 并校验为 pydantic 模型。

    解析/校验失败按 AGENTS.md 走重试路径：附加"只输出 JSON"的纠偏指令重试。
    """
    last_err: Exception | None = None
    reminder = ""
    for attempt in range(retries + 1):
        try:
            raw = llm.invoke(prompt + reminder)
            content = raw.content if hasattr(raw, "content") else str(raw)
            if isinstance(content, list):  # 多模态内容块
                content = "".join(
                    p.get("text", "") if isinstance(p, dict) else str(p) for p in content
                )
            return model.model_validate(json.loads(_extract_json(content)))
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = exc
            reminder = "\n\n【重试】你上一次的输出不是合法 JSON（可能被截断）。请精简内容并只输出一个完整、以 { 开头、以 } 结尾的 JSON 对象。"
    raise RuntimeError(f"结构化输出重试 {retries} 次后仍失败: {last_err}")


def make_cartographer(llm):
    template = _load_prompt("cartographer")

    def node(state: CaseFile) -> dict:
        packet = _evidence_packet(state)
        verdict = _structured(llm, template.replace("<<<EVIDENCE>>>", packet.text), DetectiveVerdict)
        verdict.agent = "cartographer"
        verdict.evidence = resolve_citations(verdict.findings, verdict.citations, packet.sources)
        return {"verdict_cartographer": verdict}

    return node


def make_reader(llm):
    template = _load_prompt("reader")

    def node(state: CaseFile) -> dict:
        packet = _evidence_packet(state)
        verdict = _structured(llm, template.replace("<<<EVIDENCE>>>", packet.text), DetectiveVerdict)
        verdict.agent = "reader"
        verdict.evidence = resolve_citations(verdict.findings, verdict.citations, packet.sources)
        return {"verdict_reader": verdict}

    return node


def make_auditor(llm):
    template = _load_prompt("auditor")

    def node(state: CaseFile) -> dict:
        packet = _evidence_packet(state)
        verdict = _structured(llm, template.replace("<<<EVIDENCE>>>", packet.text), DetectiveVerdict)
        verdict.agent = "auditor"
        verdict.evidence = resolve_citations(verdict.findings, verdict.citations, packet.sources)
        return {"verdict_auditor": verdict}

    return node


def _degraded_report(state: CaseFile) -> FinalReport:
    """主笔 LLM 失败时的确定性兜底报告（AGENTS.md：校验失败走降级路径）。"""
    risks = []
    if state.risk_report is not None:
        risks = [f"{f.path}: {f.message}" for f in state.risk_report.findings[:6]]
    return FinalReport(
        repo_name=state.repo.name if state.repo else "unknown",
        onboarding=["克隆仓库并阅读 README", "按架构图从核心模块读起", "运行测试套件验证环境"],
        risks=risks,
        degraded=True,
    )


def make_chief(llm):
    template = _load_prompt("chief")

    def node(state: CaseFile) -> dict:
        packet = _evidence_packet(state, char_budget=6_000)
        verdicts = [
            v
            for v in (state.verdict_cartographer, state.verdict_reader, state.verdict_auditor)
            if v is not None
        ]
        try:
            summaries = [v.model_dump(exclude={"evidence", "citations"}) for v in verdicts]
            for summary, verdict in zip(summaries, verdicts):
                summary["evidence"] = [e.model_dump(exclude={"sources"}) for e in verdict.evidence]
            prompt = template.replace("<<<VERDICTS>>>", json.dumps(summaries, ensure_ascii=False)[:6_000])
            prompt = prompt.replace("<<<EVIDENCE>>>", packet.text)
            report = _structured(llm, prompt, FinalReport)
            report.degraded = False
        except RuntimeError:
            report = _degraded_report(state)
        # 确定性优先：架构图由依赖图渲染（AGENTS.md §2.8），评分由编排层回填
        if state.repo_map is not None:
            from reposleuth_report import mermaid_from_repo_map

            report.mermaid = mermaid_from_repo_map(state.repo_map)
        report.scores = {v.agent: v.score for v in verdicts}
        if state.repo is not None:
            report.repo_name = state.repo.name
        if report.degraded and state.risk_report is not None:
            report.risk_citations = [CitationRequest(
                claim_index=i,
                source_ids=[source.id for source in packet.sources
                            if source.path == finding.path and source.start_line <= finding.line <= source.end_line][:3],
            ) for i, finding in enumerate(state.risk_report.findings[:6])]
        report.onboarding_evidence = resolve_citations(report.onboarding, report.onboarding_citations, packet.sources)
        report.risk_evidence = resolve_citations(report.risks, report.risk_citations, packet.sources)
        if report.degraded:
            for evidence in report.onboarding_evidence:
                evidence.basis = "fallback"
            for evidence in report.risk_evidence:
                evidence.basis = "rule"
        return {"report": report}

    return node
