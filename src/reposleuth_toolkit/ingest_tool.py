"""仓库文本化：目录树 + 字符预算内的代码内容，供 LLM 阅读分析。

自带实现（排序确定、预算可控），不硬依赖 gitingest；如果后续需要
gitingest 的更多能力（gitignore 感知等），在本层替换实现即可，
上层 Agent 与契约不变。
"""

from __future__ import annotations

import os
from pathlib import Path

from .models import IngestResult

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".idea", "build", "dist", ".tox", ".mypy_cache",
}

TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb", ".rs",
    ".c", ".h", ".cpp", ".cs", ".md", ".txt", ".toml", ".yaml", ".yml",
    ".cfg", ".ini", ".sql", ".sh", ".bat",
}
TEXT_FILES = {".env", "dockerfile", "makefile"}


def _build_tree(root: Path, max_entries: int = 400) -> str:
    """ASCII 目录树，条目数封顶防止超大仓库撑爆 prompt。"""
    lines: list[str] = [f"{root.name}/"]
    count = 0

    def walk(dir_path: Path, prefix: str) -> bool:  # 返回 True 表示已截断
        nonlocal count
        entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))
        for entry in entries:
            if count >= max_entries:
                lines.append(f"{prefix}...(超过 {max_entries} 条，已截断)")
                return True
            if entry.name in SKIP_DIRS:
                continue
            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                count += 1
                if walk(entry, prefix + "  "):
                    return True
            else:
                lines.append(f"{prefix}{entry.name}")
                count += 1
        return False

    walk(root, "")
    return "\n".join(lines)


def _iter_text_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix.lower() in TEXT_EXTS or name.lower() in TEXT_FILES:
                yield p


def ingest_repo(
    repo_path: str | Path,
    max_total_chars: int = 200_000,
    max_file_chars: int = 8_000,
) -> IngestResult:
    """目录树 + 代码内容拼装，总字符不超过 max_total_chars。

    - 单文件超过 max_file_chars 先截断（保留开头，通常含 imports/签名）；
    - 预算耗尽后剩余文件记入 truncated_files，供 Agent 决定是否精读。
    """
    root = Path(repo_path).resolve()
    tree_text = _build_tree(root)

    parts: list[str] = []
    truncated: list[str] = []
    budget = max_total_chars - len(tree_text)

    for path in _iter_text_files(root):
        rel = path.relative_to(root).as_posix()
        if budget <= 0:
            truncated.append(rel)
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > max_file_chars:
            text = text[:max_file_chars] + "\n...[文件过长已截断]"
        header = f"\n### {rel}\n"
        chunk = header + text
        if len(chunk) > budget:
            truncated.append(rel)
            continue
        parts.append(chunk)
        budget -= len(chunk)

    content_text = "".join(parts)
    return IngestResult(
        repo_name=root.name,
        tree_text=tree_text,
        content_text=content_text,
        truncated_files=truncated,
        total_chars=len(tree_text) + len(content_text),
    )
