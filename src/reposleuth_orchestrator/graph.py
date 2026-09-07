"""build_graph：直连模式状态机。

acquire → survey → {cartographer, reader, auditor 并行} → chief → END
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from .agents import make_auditor, make_cartographer, make_chief, make_reader
from .nodes import DEFAULT_CACHE_DIR, acquire_node, survey_node
from .state import CaseFile


def build_graph(llm, cache_dir: Path = DEFAULT_CACHE_DIR):
    """组装并编译状态机。

    llm: 任意 BaseChatModel（生产用真实模型，测试用 fake），由调用方注入。
    cache_dir: 仓库克隆缓存目录。
    """
    g = StateGraph(CaseFile)

    def _acquire(state: CaseFile) -> dict:
        return acquire_node(state, cache_dir=cache_dir)

    g.add_node("acquire", _acquire)
    g.add_node("survey", survey_node)
    g.add_node("cartographer", make_cartographer(llm))
    g.add_node("reader", make_reader(llm))
    g.add_node("auditor", make_auditor(llm))
    g.add_node("chief", make_chief(llm))

    g.add_edge(START, "acquire")
    g.add_edge("acquire", "survey")
    for agent in ("cartographer", "reader", "auditor"):
        g.add_edge("survey", agent)
        g.add_edge(agent, "chief")
    g.add_edge("chief", END)

    return g.compile()
