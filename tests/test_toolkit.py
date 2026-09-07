"""feat/toolkit 验收测试：不依赖 LLM 与网络，对本地样例仓库跑通全部工具。

验收标准（对应任务 #1）：
- clone_repo 能克隆本地路径并测量体积/语言；
- analyze_repo_map 产出正确的模块节点/导入边/外部依赖；
- scan_risks 命中预置的风险样例（凭据/eval/SQL 拼接）；
- ingest_repo 输出树与内容且预算可控。
"""

from __future__ import annotations

import json

import pytest

from reposleuth_toolkit import (
    RepoTooLarge,
    analyze_repo_map,
    clone_repo,
    ingest_repo,
    scan_risks,
)


@pytest.fixture()
def sample_repo(tmp_path):
    """构造一个微型但特征齐全的 Python 仓库。"""
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
    (app / "db.py").write_text(
        'def get_user(uid):\n    q = "SELECT * FROM users WHERE id=" + uid\n    return q\n',
        encoding="utf-8",
    )
    (root / "settings.py").write_text(
        'API_KEY = "sk-live-abcdefgh123456"\n',
        encoding="utf-8",
    )
    (root / ".env").write_text('DATABASE_PASSWORD="real-secret-123"\n', encoding="utf-8")
    return root


def test_clone_local_path(sample_repo, tmp_path):
    info = clone_repo(str(sample_repo), tmp_path / "clones", name="sample-clone")
    assert info.language.value == "python"
    assert info.file_count >= 7  # 6 个代码/配置文件
    assert (tmp_path / "clones" / "sample-clone" / "settings.py").exists()


def test_repo_map(sample_repo):
    repo_map = analyze_repo_map(sample_repo, repo_name="sample")
    module_paths = {m.path for m in repo_map.modules}
    assert {"app", "app.const", "app.utils", "app.main", "app.db", "settings"} <= module_paths

    edge_pairs = {(e.source, e.target) for e in repo_map.edges}
    assert ("app.main", "app.utils") in edge_pairs      # from app.utils import helper
    assert ("app.utils", "app.const") in edge_pairs     # from . import const
    assert all(not src.startswith("external") for src, _ in edge_pairs)

    assert "requests" in repo_map.external_deps         # 第三方
    assert "os" not in repo_map.external_deps           # 标准库被排除
    assert repo_map.stats["files"] == 6
    assert repo_map.stats["total_loc"] > 0


def test_risk_scan(sample_repo):
    report = scan_risks(sample_repo, engine="builtin")
    assert report.engine == "builtin"
    assert report.scanned_files >= 7

    by_rule = {}
    for f in report.findings:
        by_rule.setdefault(f.rule_id, []).append(f)

    assert "RS001-SECRET" in by_rule                    # settings.py 的 API_KEY
    assert "RS005-EVAL" in by_rule                      # utils.py 的 eval
    assert "RS003-SQL-CONCAT" in by_rule                # db.py 的 SQL 拼接

    # 占位符不误报
    assert all(
        "example" not in f.message.lower() or f.rule_id != "RS001-SECRET"
        for f in report.findings
    )
    summary = report.summary()
    assert summary["critical"] >= 2 and summary["high"] >= 1


def test_risk_scan_placeholder_not_reported(tmp_path):
    root = tmp_path / "ph"
    root.mkdir()
    (root / "conf.py").write_text(
        'API_KEY = "your-api-key-here"\nTOKEN = "${ENV_TOKEN}"\nAPI_KEY = "sk-real-abc123456"\n',
        encoding="utf-8",
    )
    report = scan_risks(root)
    secret_lines = [f.line for f in report.findings if f.rule_id == "RS001-SECRET"]
    assert secret_lines == [3]  # 只命中真实的第三行


def test_ingest_repo(sample_repo):
    result = ingest_repo(sample_repo, max_total_chars=50_000)
    assert "app/" in result.tree_text
    assert "### settings.py" in result.content_text
    assert "API_KEY" in result.content_text
    assert result.truncated_files == []
    assert result.total_chars <= 50_000


def test_ingest_budget_truncation(sample_repo):
    result = ingest_repo(sample_repo, max_total_chars=400, max_file_chars=200)
    assert len(result.truncated_files) >= 1
    assert result.total_chars <= 400 + 1


def test_clone_rejects_oversize(sample_repo, tmp_path):
    """克隆后体积预检：把阈值压到 0 应触发 RepoTooLarge 并清理目录。"""
    with pytest.raises(RepoTooLarge):
        clone_repo(str(sample_repo), tmp_path / "clones", name="tiny", max_files=1)
    assert not (tmp_path / "clones" / "tiny").exists()  # 超限目录已清理


def test_langchain_tools_export():
    """@tool 封装层可导入、可拿到工具清单（需要 agent extra）。"""
    from reposleuth_toolkit.langchain_tools import get_langchain_tools

    tools = get_langchain_tools()
    assert {t.name for t in tools} == {
        "clone_repo_tool", "repo_map_tool", "risk_scan_tool", "ingest_repo_tool",
        "github_search_tool",
    }
    # 直接调用一次验证 JSON 输出
    sample = json.loads(
        __import__("reposleuth_toolkit.langchain_tools", fromlist=["risk_scan_tool"])
        .risk_scan_tool.invoke({"repo_path": str(_make_repo())})
    )
    assert "findings" in sample


def _make_repo():
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp()) / "mini"
    root.mkdir()
    (root / "a.py").write_text("password = 'super-secret-xyz-9876'\n", encoding="utf-8")
    return root
