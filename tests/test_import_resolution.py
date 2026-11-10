"""仓库分析基础能力的离线回归测试。"""

from __future__ import annotations

from pathlib import Path

from reposleuth_toolkit import analyze_repo_map


def test_root_module_named_src_is_not_dropped(tmp_path: Path) -> None:
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert {m.path for m in analyze_repo_map(tmp_path).modules} == {"src"}


def test_src_layout_resolves_absolute_internal_imports(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text("def run(): pass\n", encoding="utf-8")
    (tmp_path / "test_demo.py").write_text("from demo.core import run\n", encoding="utf-8")
    result = analyze_repo_map(tmp_path)
    assert {m.path for m in result.modules} == {"demo", "demo.core", "test_demo"}
    assert {(e.source, e.target) for e in result.edges} == {("test_demo", "demo.core")}
    assert "demo" not in result.external_deps


def test_package_relative_imports_resolve_to_existing_modules(tmp_path: Path) -> None:
    pkg = tmp_path / "demo"
    nested = pkg / "nested"
    nested.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from .core import run\n", encoding="utf-8")
    (pkg / "core.py").write_text("def run(): pass\n", encoding="utf-8")
    (nested / "__init__.py").write_text("from ..core import run\n", encoding="utf-8")
    (nested / "consumer.py").write_text(
        "from ..core import run\nfrom .. import core\nfrom ..missing import nope\n",
        encoding="utf-8",
    )
    result = analyze_repo_map(tmp_path)
    assert {(e.source, e.target) for e in result.edges} == {
        ("demo", "demo.core"), ("demo.nested", "demo.core"), ("demo.nested.consumer", "demo.core"),
    }
    assert all(e.target in {m.path for m in result.modules} for e in result.edges)


def test_src_as_real_package_keeps_its_name(tmp_path: Path) -> None:
    pkg = tmp_path / "src"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .core import run\n", encoding="utf-8")
    (pkg / "core.py").write_text("def run(): pass\n", encoding="utf-8")
    result = analyze_repo_map(tmp_path)
    assert {m.path for m in result.modules} == {"src", "src.core"}
    assert {(e.source, e.target) for e in result.edges} == {("src", "src.core")}
