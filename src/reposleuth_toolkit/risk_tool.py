"""风险扫描：内置正则规则库（零依赖、离线可用），semgrep 可用时可选增强。

规则覆盖最常见的高危模式：硬编码凭据、私钥内嵌、SQL 拼接、eval/exec、
shell=True。内置规则刻意保守（排除占位符），宁可漏报不误报——
v1 的目标是给侦探 Agent 提供线索，不是替代 SAST。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .models import RiskFinding, RiskReport, Severity

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".idea", "build", "dist", ".min", "vendor",
}

SCAN_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb", ".php",
    ".c", ".cpp", ".h", ".cs", ".sql", ".sh", ".yaml", ".yml", ".toml",
    ".cfg", ".ini",
}
SCAN_FILES = {".env", "dockerfile", "makefile"}


class _Rule:
    def __init__(self, rule_id: str, severity: Severity, pattern: re.Pattern, message: str):
        self.rule_id = rule_id
        self.severity = severity
        self.pattern = pattern
        self.message = message


_SECRET_RE = re.compile(
    # 不加前导 \b：DATABASE_PASSWORD / MY_SECRET 这类前缀组合也要命中
    r"""(?ix)(?:api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token|password|passwd|pwd)\b"""
    r"""\s*[:=]\s*["']([^"']{8,})["']"""
)

BUILTIN_RULES: list[_Rule] = [
    _Rule("RS001-SECRET", Severity.critical, _SECRET_RE, "疑似硬编码凭据"),
    _Rule(
        "RS002-PRIVATE-KEY", Severity.critical,
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "疑似私钥内嵌于代码",
    ),
    _Rule(
        "RS003-SQL-CONCAT", Severity.high,
        re.compile(r"""(?i)["'](?:\s*)(?:select|insert\s+into|update|delete\s+from)\b[^"']*["']\s*\+"""),
        "疑似 SQL 字符串拼接",
    ),
    _Rule(
        "RS004-SQL-FSTRING", Severity.high,
        re.compile(r"""(?i)f["'][^"']*\b(?:select|insert\s+into|update|delete\s+from)\b"""),
        "疑似 f-string SQL 拼接",
    ),
    _Rule(
        "RS005-EVAL", Severity.medium,
        re.compile(r"\b(?:eval|exec)\s*\("),
        "使用 eval/exec 动态执行代码",
    ),
    _Rule(
        "RS006-SHELL-TRUE", Severity.medium,
        re.compile(r"shell\s*=\s*True"),
        "subprocess 启用 shell=True",
    ),
]

# 占位符排除：your_key / example / ${VAR} / <TODO> 等
_PLACEHOLDER_RE = re.compile(
    r"""(?ix)(?:your[\w-]*|xxx[\w-]*|example[\w-]*|sample[\w-]*|placeholder[\w-]*|changeme[\w-]*|dummy[\w-]*|\$\{[^}]*\}|<[^>]*>)"""
)


def _iter_scan_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in SCAN_EXTS or name.lower() in SCAN_FILES:
                yield p


def _scan_file_builtin(path: Path, root: Path) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    rel = path.relative_to(root).as_posix()
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or len(line) > 500:
            continue
        if stripped.startswith(("#", "//")):
            continue  # 纯注释行不扫，减少误报
        for rule in BUILTIN_RULES:
            m = rule.pattern.search(line)
            if not m:
                continue
            if rule.rule_id == "RS001-SECRET" and m.lastindex:
                if _PLACEHOLDER_RE.search(m.group(1)):
                    continue
            findings.append(
                RiskFinding(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    path=rel,
                    line=lineno,
                    message=rule.message,
                )
            )
    return findings


def _scan_semgrep(root: Path) -> list[RiskFinding]:
    """调用本机 semgrep（需已安装），失败时抛异常由上层回退。"""
    proc = subprocess.run(
        ["semgrep", "scan", "--json", "--quiet", "--config", "auto", str(root)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    data = json.loads(proc.stdout or "{}")
    findings: list[RiskFinding] = []
    for item in data.get("results", []):
        extra = item.get("extra", {})
        sev_map = {"ERROR": Severity.critical, "WARNING": Severity.high, "INFO": Severity.low}
        findings.append(
            RiskFinding(
                rule_id=item.get("check_id", "semgrep-unknown"),
                severity=sev_map.get(extra.get("severity", "").upper(), Severity.medium),
                path=Path(item.get("path", "")).as_posix(),
                line=item.get("start", {}).get("line", 0),
                message=extra.get("message", ""),
                engine="semgrep",
            )
        )
    return findings


def scan_risks(repo_path: str | Path, engine: str = "builtin") -> RiskReport:
    """扫描仓库风险。engine: builtin | semgrep | auto（auto 失败回退 builtin）。"""
    root = Path(repo_path).resolve()
    files = list(_iter_scan_files(root))

    findings: list[RiskFinding] = []
    used_engine = "builtin"

    if engine in ("semgrep", "auto") and shutil.which("semgrep"):
        try:
            findings = _scan_semgrep(root)
            used_engine = "semgrep"
        except Exception:
            if engine == "semgrep":
                raise
            findings = []
    if not findings:
        for path in files:
            findings.extend(_scan_file_builtin(path, root))
        used_engine = "builtin"

    return RiskReport(
        repo_name=root.name,
        engine=used_engine,
        scanned_files=len(files) if used_engine == "builtin" else len({f.path for f in findings}),
        findings=findings,
    )
