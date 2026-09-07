"""仓库依赖图分析：纯 AST 实现（标准库 ast + sys.stdlib_module_names），零外部依赖。

产出统一的 RepoMap（模块节点 + 内部导入边 + 外部依赖），这是三个侦探 Agent
共享的"地图"。本模块刻意不引入 pydeps/graphviz 等外部工具：
- Windows 环境零安装成本；
- 分析逻辑完全确定性、可单测；
- AST 解析只支持 Python；TS/JS 走 madge 适配，后续分支补充。
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

from .git_tool import detect_language
from .models import CallEdge, Language, ModuleNode, RepoMap

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".idea", "build", "dist", ".tox", ".mypy_cache",
}


def _walk_py(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _module_path(root: Path, file: Path) -> str | None:
    """文件路径 -> 点分模块路径；__init__.py 归一为包路径；非法目录名返回 None。"""
    rel = file.relative_to(root)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    if not all(p.isidentifier() for p in parts):
        return None
    return ".".join(parts)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve_import(
    name: str,
    level: int,
    cur_module: str,
    module_set: set[str],
) -> tuple[str, str | None]:
    """解析一条 import。

    返回 (kind, target)：
    - ("internal", 模块路径)：内部导入边；
    - ("external", 顶层包名)：第三方依赖；
    - ("stdlib", None)：标准库，忽略。
    """
    if level == 0:
        top = name.split(".")[0]
        if top in sys.stdlib_module_names:
            return "stdlib", None
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            cand = ".".join(parts[:i])
            if cand in module_set:
                return "internal", cand
        return "external", top

    # 相对导入：level=1 是当前包，每多一级向上走一层
    pkg_parts = cur_module.split(".")[:-1]
    up = level - 1
    if up:
        pkg_parts = pkg_parts[:-up] if len(pkg_parts) >= up else []
    base_parts = pkg_parts + ([name] if name else [])
    base = ".".join(base_parts)
    return ("internal", base) if base else ("stdlib", None)


def analyze_repo_map(repo_path: str | Path, repo_name: str | None = None) -> RepoMap:
    """分析 Python 仓库，产出 RepoMap。不调用 LLM，完全确定性。"""
    root = Path(repo_path).resolve()

    lang = detect_language(root)
    if lang not in (Language.python, Language.unknown):
        raise NotImplementedError(
            f"当前仅支持 Python 仓库（检测到 {lang.value}）；TS/JS 走 madge 适配，后续分支补充"
        )

    py_files = list(_walk_py(root))

    modules: dict[str, ModuleNode] = {}
    for f in py_files:
        mp = _module_path(root, f)
        if mp is None:
            continue
        loc = len(_read(f).splitlines())
        modules[mp] = ModuleNode(name=mp.rsplit(".", 1)[-1], path=mp, loc=loc)

    module_set = set(modules)
    edges: dict[tuple[str, str], CallEdge] = {}
    external: set[str] = set()

    for f in py_files:
        mp = _module_path(root, f)
        if mp is None:
            continue
        try:
            tree = ast.parse(_read(f))
        except SyntaxError:
            continue

        candidates: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates.extend((alias.name, 0) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for alias in node.names:
                    if alias.name == "*":
                        if base:
                            candidates.append((base, node.level or 0))
                    else:
                        full = f"{base}.{alias.name}" if base else alias.name
                        candidates.append((full, node.level or 0))

        for name, level in candidates:
            if not name:
                continue
            kind, target = _resolve_import(name, level, mp, module_set)
            if kind == "internal" and target and target != mp:
                edges[(mp, target)] = CallEdge(source=mp, target=target)
            elif kind == "external" and target:
                external.add(target)

    edge_list = sorted(edges.values(), key=lambda e: (e.source, e.target))
    return RepoMap(
        repo_name=repo_name or root.name,
        language=Language.python,
        modules=sorted(modules.values(), key=lambda m: m.path),
        edges=edge_list,
        external_deps=sorted(external),
        stats={
            "files": len(py_files),
            "modules": len(modules),
            "internal_edges": len(edge_list),
            "external_deps": len(external),
            "total_loc": sum(m.loc for m in modules.values()),
        },
    )
