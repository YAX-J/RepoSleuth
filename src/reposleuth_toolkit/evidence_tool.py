"""无状态证据工具：生成脱敏源码片段并按白名单校验引用，不判断结论语义。"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

from .models import CitationRequest, ClaimEvidence, RepoInfo, SourceExcerpt


def _source_url(repo: RepoInfo | None, path: str, start: int, end: int) -> str:
    if repo is None or not re.fullmatch(r"[0-9a-f]{40,64}", repo.commit_sha):
        return ""
    parsed = urlsplit(repo.url)
    if parsed.hostname == "github.com" and parsed.scheme in {"https", "http", "ssh"}:
        full_name = parsed.path.strip("/").removesuffix(".git")
    elif match := re.fullmatch(r"git@github\.com:([\w.-]+/[\w.-]+?)(?:\.git)?/?", repo.url):
        full_name = match.group(1)
    else:
        return ""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", full_name):
        return ""
    return f"https://github.com/{full_name}/blob/{repo.commit_sha}/{quote(path, safe='/')}#L{start}-L{end}"


def build_source_excerpts(
    path: str, text: str, first_id: int, repo: RepoInfo | None = None,
) -> list[SourceExcerpt]:
    """将已脱敏文本按最多 20 行、1200 字符分片，保留原始行号并生成固定版本链接。"""
    lines = text.splitlines()
    sources: list[SourceExcerpt] = []
    cursor = 0
    while cursor < len(lines):
        start = cursor
        selected: list[str] = []
        length = 0
        while cursor < len(lines) and len(selected) < 20:
            line = lines[cursor][:1200]
            cost = len(line) + (1 if selected else 0)
            if selected and length + cost > 1200:
                break
            selected.append(line)
            length += cost
            cursor += 1
        sources.append(SourceExcerpt(
            id=f"s{first_id + len(sources)}", path=path, start_line=start + 1,
            end_line=cursor, snippet="\n".join(selected),
            url=_source_url(repo, path, start + 1, cursor),
        ))
    return sources


def resolve_citations(
    claims: list[str], requests: list[CitationRequest], available: list[SourceExcerpt],
) -> list[ClaimEvidence]:
    """仅接受实际提供的完整片段；未知 ID、重复结论索引或混合伪造引用均拒绝。"""
    by_id = {source.id: source for source in available}
    results: list[ClaimEvidence] = []
    for index in range(len(claims)):
        matches = [request for request in requests if request.claim_index == index]
        if not matches or (len(matches) == 1 and not matches[0].source_ids):
            results.append(ClaimEvidence(claim_index=index, status="missing", reason="未提供引用"))
            continue
        if len(matches) != 1 or any(source_id not in by_id for source_id in matches[0].source_ids):
            results.append(ClaimEvidence(claim_index=index, status="invalid", reason="引用不存在、未展示或索引重复"))
            continue
        sources = [by_id[source_id] for source_id in dict.fromkeys(matches[0].source_ids)]
        results.append(ClaimEvidence(claim_index=index, status="verified", sources=sources))
    return results
