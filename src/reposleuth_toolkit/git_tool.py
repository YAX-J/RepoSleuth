"""git 克隆工具：浅克隆 + 双重体积预检（克隆前 GitHub API / 克隆后本地测量）。

设计要点：
- 预检不过直接拒绝，避免浪费带宽和磁盘；
- 本地路径也接受（测试与离线场景）；
- 纯确定性逻辑，不依赖 LLM。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .models import Language, RepoInfo

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".idea"}

GITHUB_URL_RE = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")

LANG_EXTS: dict[Language, set[str]] = {
    Language.python: {".py"},
    Language.typescript: {".ts", ".tsx"},
    Language.javascript: {".js", ".jsx"},
}


class RepoTooLarge(Exception):
    """仓库体积/文件数超过预检阈值。"""


class RepoCloneError(RuntimeError):
    """获取仓库失败，包括 git 子进程超时。"""


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RepoCloneError("git 操作超过 120 秒，已终止") from exc


def _github_size_mb(url: str) -> float | None:
    """通过 GitHub API 预检仓库体积；非 GitHub 或请求失败返回 None。"""
    m = GITHUB_URL_RE.search(url)
    if not m:
        return None
    api = f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}"
    try:
        req = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        # API 的 size 单位是 KB
        return float(data.get("size", 0)) / 1024.0
    except Exception:
        return None


def _repo_name(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    return tail.removesuffix(".git")


def _source_hash(url: str, local_dir: Path | None) -> str:
    """按来源计算缓存指纹；本地路径规范化，GitHub 支持 HTTPS/SSH 等价地址。"""
    if local_dir is not None:
        identity = os.path.normcase(str(local_dir.resolve()))
    else:
        parsed = urllib.parse.urlsplit(url)
        github_match = re.fullmatch(r"git@github\.com:([\w.-]+/[\w.-]+?)(?:\.git)?/?", url)
        if parsed.hostname == "github.com" and parsed.scheme in {"https", "http", "ssh"}:
            identity = "github.com/" + parsed.path.strip("/").removesuffix(".git").casefold()
        elif github_match:
            identity = "github.com/" + github_match.group(1).casefold()
        else:
            identity = url.rstrip("/").removesuffix(".git")
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def _measure(root: Path) -> tuple[int, int]:
    files = list(_walk_files(root))
    return len(files), sum(f.stat().st_size for f in files)


def detect_language(repo_path: str | Path) -> Language:
    counts: dict[Language, int] = {}
    for f in _walk_files(Path(repo_path)):
        for lang, exts in LANG_EXTS.items():
            if f.suffix in exts:
                counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return Language.unknown
    return max(counts, key=lambda k: counts[k])


def _as_local_dir(url: str) -> Path | None:
    """url 指向本地已存在目录时返回该目录，否则 None。"""
    p = Path(url)
    return p if p.is_absolute() and p.is_dir() else None


def _repo_revision(path: Path) -> str:
    """记录实际获取副本的 Git 提交；普通目录没有提交版本。"""
    if not (path / ".git").exists():
        return ""
    status = _run_git(["-C", str(path), "status", "--porcelain", "--untracked-files=all", "--ignored=matching"])
    if status.returncode != 0 or status.stdout.strip():
        return ""
    proc = _run_git(["-C", str(path), "rev-parse", "HEAD"])
    revision = proc.stdout.strip()
    return revision if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", revision) else ""


def clone_repo(
    url: str,
    dest_parent: str | Path,
    name: str | None = None,
    max_size_mb: float = 50,
    max_files: int = 2000,
    reuse: bool = True,
) -> RepoInfo:
    """获取仓库副本并返回 RepoInfo；默认缓存目录按来源隔离。

    - GitHub URL：克隆前用 API 预检体积；
    - 本地 git 仓库：直接 git clone；
    - 本地普通目录（测试/离线）：copytree 回退，跳过 SKIP_DIRS；
    - 默认缓存目录附加来源指纹；显式 name 保持指定目录名；
    - reuse=True 仅复用来源指纹一致的缓存，旧的未验证缓存拒绝复用；
    - 克隆后再次测量，超限则删除目录并抛 RepoTooLarge。
    """
    dest_parent = Path(dest_parent).resolve()
    src = _as_local_dir(url)
    name_provided = name is not None
    name = name if name_provided else (src.name if src is not None else _repo_name(url))
    if not name or name in {".", ".."} or "/" in name or "\\" in name or Path(name).is_absolute():
        raise ValueError("仓库缓存名称必须是单个目录名")
    source_hash = _source_hash(url, src)
    cache_name = name if name_provided else f"{name}-{source_hash[:12]}"
    dest = dest_parent / cache_name
    if dest.resolve() != dest or dest.resolve().parent != dest_parent:
        raise ValueError("仓库缓存目录不能指向目标父目录之外或使用符号链接")
    if src is not None and not (src / ".git").exists() and dest.is_relative_to(src.resolve()):
        raise ValueError("普通本地目录的缓存必须放在源目录之外，避免递归复制")
    # 指纹旁文件不进入仓库分析范围，也不保存 URL 中可能包含的凭据。
    origin_file = dest_parent / f".{cache_name}.reposleuth-origin"

    if dest.exists() and any(dest.iterdir()):
        if reuse:
            try:
                verified = origin_file.read_text(encoding="utf-8").strip() == source_hash
            except (OSError, UnicodeError):
                verified = False
            if not verified:
                raise FileExistsError(f"缓存来源不匹配或无法验证，请使用其他缓存目录：{dest}")
            file_count, total = _measure(dest)
            # 复用分支同样要执行阈值检查，否则超限仓库会绕过预检
            if file_count > max_files or total / 1024 / 1024 > max_size_mb:
                raise RepoTooLarge(
                    f"复用目录预检：{file_count} 个文件 / {total / 1024 / 1024:.1f}MB "
                    f"超过阈值（{max_files} 个文件 / {max_size_mb}MB）"
                )
            return RepoInfo(
                name=name,
                url=url,
                local_path=str(dest),
                language=detect_language(dest),
                file_count=file_count,
                total_size_bytes=total,
                commit_sha=_repo_revision(dest),
            )
        raise FileExistsError(f"目标目录已存在：{dest}")

    size_mb = _github_size_mb(url)
    if size_mb is not None and size_mb > max_size_mb:
        raise RepoTooLarge(
            f"GitHub API 预检：仓库 {size_mb:.1f}MB 超过阈值 {max_size_mb}MB"
        )

    dest_parent.mkdir(parents=True, exist_ok=True)
    if src is not None and not (src / ".git").exists():
        # 本地普通目录：直接复制，语义等价于"获取仓库副本"
        shutil.copytree(
            src, dest,
            ignore=shutil.ignore_patterns(*SKIP_DIRS),
            dirs_exist_ok=True,
        )
    else:
        # 本机代理会导致 schannel 吊销检查失败，克隆时显式关闭该检查（仅此命令生效）
        proc = _run_git(["-c", "http.sslVerify=false", "clone", "--depth", "1", url, str(dest)])
        if proc.returncode != 0:
            raise RepoCloneError(f"git clone 失败: {proc.stderr.strip()}")

    file_count, total = _measure(dest)
    total_mb = total / 1024 / 1024
    if file_count > max_files or total_mb > max_size_mb:
        shutil.rmtree(dest, ignore_errors=True)
        raise RepoTooLarge(
            f"克隆后预检：{file_count} 个文件 / {total_mb:.1f}MB "
            f"超过阈值（{max_files} 个文件 / {max_size_mb}MB）"
        )

    origin_file.write_text(source_hash + "\n", encoding="utf-8")
    return RepoInfo(
        name=name,
        url=url,
        local_path=str(dest),
        language=detect_language(dest),
        file_count=file_count,
        total_size_bytes=total,
        cloned_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        commit_sha=_repo_revision(dest),
    )
