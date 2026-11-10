"""RepoSleuth 统一数据模型 —— 各工具与 Agent 之间共享的"案卷"格式。

所有工具的输出都是这里的 Pydantic 模型，保证：
1. 编排层（LangGraph）拿到的结构是稳定契约；
2. 未来迁移为 MCP server 时可直接由模型生成 JSON Schema。
"""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator


class Language(str, Enum):
    python = "python"
    typescript = "typescript"
    javascript = "javascript"
    unknown = "unknown"


class RepoInfo(BaseModel):
    """clone_repo 的产物：仓库元信息。"""

    name: str
    url: str
    local_path: str
    language: Language = Language.unknown
    file_count: int = 0
    total_size_bytes: int = 0
    cloned_at: str = ""
    commit_sha: str = ""


class ModuleNode(BaseModel):
    """依赖图中的一个模块（文件级）。"""

    name: str
    path: str  # 点分模块路径，如 app.main
    loc: int = 0


class CallEdge(BaseModel):
    """一条内部导入边：source 模块引用了 target 模块。"""

    source: str
    target: str
    kind: str = "import"


class RepoMap(BaseModel):
    """静态分析产物：模块节点 + 导入边 + 外部依赖。

    这是三个侦探 Agent 共享的"地图"，全部来自确定性 AST 分析，不经过 LLM。
    """

    repo_name: str
    language: Language = Language.unknown
    modules: list[ModuleNode] = Field(default_factory=list)
    edges: list[CallEdge] = Field(default_factory=list)
    external_deps: list[str] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)


class RepoCandidate(BaseModel):
    """GitHub 搜索返回的候选仓库（scouting 阶段使用）。"""

    full_name: str = Field(description="owner/repo")
    html_url: str
    description: str = ""
    stars: int = 0
    language: str = ""
    size_kb: int = 0


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class RiskFinding(BaseModel):
    rule_id: str
    severity: Severity
    path: str  # 仓库相对路径
    line: int
    message: str
    engine: str = "builtin"  # builtin | semgrep


class RiskReport(BaseModel):
    repo_name: str
    engine: str = "builtin"
    scanned_files: int = 0
    findings: list[RiskFinding] = Field(default_factory=list)

    def summary(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for f in self.findings:
            out[f.severity.value] += 1
        return out


class SourceExcerpt(BaseModel):
    """工具层生成的脱敏源码片段；行号对应原文件，不由模型编造。"""

    id: str = Field(pattern=r"^s[0-9]+$")
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    snippet: str
    url: str = ""

    @model_validator(mode="after")
    def validate_range(self) -> SourceExcerpt:
        """拒绝倒置行号及仓库之外的文件路径。"""
        path = PurePosixPath(self.path)
        if self.end_line < self.start_line:
            raise ValueError("源码片段行号范围倒置")
        if path.is_absolute() or ".." in path.parts or "\\" in self.path or ":" in self.path:
            raise ValueError("源码片段必须使用仓库内的相对路径")
        if not self.path or any(ord(c) < 32 for c in self.path):
            raise ValueError("源码路径不能为空或包含控制字符")
        if self.url:
            parsed = urlsplit(self.url)
            if parsed.scheme != "https" or parsed.netloc != "github.com":
                raise ValueError("源码链接必须使用 GitHub HTTPS 地址")
        return self


class CitationRequest(BaseModel):
    """模型对一条结论提出的引用请求；只能使用证据包中的片段 ID。"""

    claim_index: int = Field(ge=0)
    source_ids: list[str] = Field(default_factory=list, max_length=3)


class ClaimEvidence(BaseModel):
    """编排层校验后的引用结果；位置有效不等同于结论语义正确。"""

    claim_index: int = Field(ge=0)
    status: Literal["verified", "missing", "invalid"]
    sources: list[SourceExcerpt] = Field(default_factory=list)
    reason: str = ""
    basis: Literal["model", "rule", "fallback"] = "model"


class EvidencePacket(BaseModel):
    """预算内的证据文本，以及其中完整展示、允许被引用的源码片段。"""

    text: str = ""
    sources: list[SourceExcerpt] = Field(default_factory=list)


class IngestResult(BaseModel):
    """仓库文本化产物：目录树 + 预算内的代码内容，供 LLM 阅读。"""

    repo_name: str
    tree_text: str
    content_text: str
    truncated_files: list[str] = Field(default_factory=list)
    total_chars: int = 0
    sources: list[SourceExcerpt] = Field(default_factory=list)
