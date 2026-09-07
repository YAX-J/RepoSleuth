"""feat/investigation 冒烟测试：GenericFakeChatModel 脚本化响应，端到端跑通状态机。

验收（对应任务 #2 直连模式）：
- 给定本地样例仓库路径，状态机完整走完 acquire → survey → 三侦探 → chief；
- 三侦探结论各自落位、主笔 scores 由编排层回填（fake 返回的 scores 为空 {}）；
- 全程不依赖网络与真实 LLM。
"""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from reposleuth_orchestrator import build_graph


@pytest.fixture()
def sample_repo(tmp_path):
    """与 toolkit 验收同款微型仓库：含内部依赖、第三方依赖与风险样例。"""
    root = tmp_path / "sample"
    app = root / "app"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "const.py").write_text("MAGIC = 42\n", encoding="utf-8")
    (app / "utils.py").write_text(
        "from . import const\n\n\ndef helper():\n    return eval('1+2') + const.MAGIC\n",
        encoding="utf-8",
    )
    (app / "main.py").write_text(
        "from app.utils import helper\nimport os\nimport requests\n\n\ndef run():\n    return helper()\n",
        encoding="utf-8",
    )
    (root / "settings.py").write_text(
        'API_KEY = "sk-live-abcdefgh123456"\n',
        encoding="utf-8",
    )
    return root


def _scripted_llm():
    """按侦探节点注册顺序（cartographer → reader → auditor → chief）脚本化响应。"""

    def verdict(agent: str, score: int) -> str:
        return json.dumps(
            {"agent": agent, "score": score, "findings": ["finding-1"], "notes": "ok"}
        )

    report = json.dumps(
        {
            "repo_name": "sample",
            "onboarding": ["读 app/main.py", "跑测试"],
            "risks": ["settings.py 疑似硬编码凭据"],
            "scores": {},
        }
    )
    msgs = [verdict("cartographer", 7), verdict("reader", 6), verdict("auditor", 8), report]
    return GenericFakeChatModel(messages=iter(AIMessage(content=m) for m in msgs))


def test_graph_end_to_end(sample_repo, tmp_path):
    graph = build_graph(_scripted_llm(), cache_dir=tmp_path / "cache")
    final = graph.invoke({"repo_url": str(sample_repo)})

    # toolkit 确定性产物落位
    assert final["repo"] is not None
    assert final["repo_map"].stats["files"] == 5
    assert "requests" in final["repo_map"].external_deps
    assert final["risk_report"].summary()["critical"] >= 1

    # 三侦探结论各自落位（并行节点执行顺序不保证，断言与顺序无关）
    assert final["verdict_cartographer"].agent == "cartographer"
    assert final["verdict_reader"].agent == "reader"
    assert final["verdict_auditor"].agent == "auditor"
    assert {final["verdict_cartographer"].score,
            final["verdict_reader"].score,
            final["verdict_auditor"].score} == {7, 6, 8}

    # 主笔汇总 + 编排层回填评分（fake 返回的 scores 必须被覆盖）
    report = final["report"]
    assert report.repo_name == "sample"
    assert report.mermaid.startswith("graph TD")
    assert set(report.scores.values()) == {7, 6, 8}
    assert set(report.scores) == {"cartographer", "reader", "auditor"}
    assert len(report.onboarding) >= 1 and len(report.risks) >= 1


def test_extract_json_tolerates_fences():
    from reposleuth_orchestrator.agents import _extract_json

    fenced = '前置废话\n```json\n{"a": 1}\n```\n后缀'
    assert _extract_json(fenced) == '{"a": 1}'
    assert _extract_json('{"b": {"c": 2}}') == '{"b": {"c": 2}}'


def test_chief_degrades_on_llm_failure(sample_repo, tmp_path):
    """主笔 LLM 持续输出非法 JSON 时，降级为确定性兜底报告而非崩溃。"""
    from langchain_core.language_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    verdict = lambda agent: json.dumps({"agent": agent, "score": 7, "findings": [], "notes": "ok"})
    bad = [AIMessage(content="```json\n{截断的垃圾输出"), AIMessage(content="不是json"), AIMessage(content="{}")]
    msgs = [AIMessage(content=verdict("cartographer")), AIMessage(content=verdict("reader")),
            AIMessage(content=verdict("auditor"))] + bad * 3
    graph = build_graph(GenericFakeChatModel(messages=iter(msgs)), cache_dir=tmp_path / "cache")
    final = graph.invoke({"repo_url": str(sample_repo)})

    report = final["report"]
    assert report.degraded is True
    assert report.mermaid.startswith("graph TD")  # 架构图仍是确定性渲染
    assert report.scores == {"cartographer": 7, "reader": 7, "auditor": 7}
