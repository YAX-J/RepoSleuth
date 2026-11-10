"""可追溯报告验收：片段、引用白名单、预算、脱敏和渲染均离线验证。"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from reposleuth_toolkit import ingest_repo
from reposleuth_toolkit.models import CitationRequest, RepoInfo, SourceExcerpt


def test_ingest_sources_keep_original_line_numbers(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'API_KEY = """synthetic-evidence-sensitive\ncontinued"""\n'
        "\ndef run():\n    return 42\n", encoding="utf-8",
    )
    result = ingest_repo(tmp_path)
    assert result.sources
    source = result.sources[0]
    assert source.path == "app.py" and source.start_line == 1 and source.end_line == 5
    assert source.snippet.splitlines()[3] == "def run():"
    assert "synthetic-evidence-sensitive" not in source.snippet
    assert "continued" not in source.snippet


def test_citation_resolution_rejects_unknown_and_duplicate_claims() -> None:
    from reposleuth_toolkit.evidence_tool import resolve_citations

    source = SourceExcerpt(id="s1", path="app.py", start_line=1, end_line=1, snippet="run()")
    result = resolve_citations(
        ["valid", "unknown", "mixed", "duplicate", "missing"],
        [CitationRequest(claim_index=0, source_ids=["s1"]),
         CitationRequest(claim_index=1, source_ids=["fabricated"]),
         CitationRequest(claim_index=2, source_ids=["s1", "fabricated"]),
         CitationRequest(claim_index=3, source_ids=["s1"]),
         CitationRequest(claim_index=3, source_ids=["s1"])],
        [source],
    )
    assert [r.status for r in result] == ["verified", "invalid", "invalid", "invalid", "missing"]
    assert result[0].sources == [source]
    assert all(not r.sources for r in result[1:])


def test_packet_only_allows_completely_visible_sources(tmp_path: Path) -> None:
    from reposleuth_orchestrator.agents import _evidence_packet
    from reposleuth_orchestrator.state import CaseFile

    (tmp_path / "app.py").write_text("VALUE = 1\n" * 300, encoding="utf-8")
    ingest = ingest_repo(tmp_path)
    packet = _evidence_packet(CaseFile(ingest=ingest), char_budget=1600)
    assert len(packet.text) <= 1600
    assert 0 < len(packet.sources) < len(ingest.sources)
    for source in packet.sources:
        assert f"[{source.id}]" in packet.text and source.snippet in packet.text


def test_unknown_or_missing_citations_are_reported_as_unverified(tmp_path: Path) -> None:
    from reposleuth_orchestrator.agents import make_reader
    from reposleuth_orchestrator.state import CaseFile

    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    class Model:
        def invoke(self, prompt: str):
            return SimpleNamespace(content=json.dumps({
                "agent":"reader", "score":7, "findings":["app.py: example", "unsupported"],
                "citations":[{"claim_index":0,"source_ids":["unknown"]}],
                "evidence":[{"claim_index":0,"status":"verified","sources":[]}],
            }))

    result = make_reader(Model())(CaseFile(ingest=ingest_repo(tmp_path)))["verdict_reader"]
    assert [r.status for r in result.evidence] == ["invalid", "missing"]


def test_github_sources_link_to_the_analyzed_commit(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    repo = RepoInfo(name="demo", url="https://github.com/owner/demo", local_path=str(tmp_path), commit_sha="a" * 40)
    source = ingest_repo(tmp_path, repo=repo).sources[0]
    assert source.url == f"https://github.com/owner/demo/blob/{'a' * 40}/app.py#L1-L1"


def test_markdown_includes_verified_sources_and_missing_evidence() -> None:
    from reposleuth_orchestrator.state import CaseFile, FinalReport
    from reposleuth_report import render_markdown
    from reposleuth_toolkit.models import ClaimEvidence

    source = SourceExcerpt(id="s1", path="app.py", start_line=1, end_line=1, snippet="run()")
    case = CaseFile(report=FinalReport(
        repo_name="demo", onboarding=["Read app.py"], risks=["Unsupported claim"],
        onboarding_evidence=[ClaimEvidence(claim_index=0,status="verified",sources=[source])],
        risk_evidence=[ClaimEvidence(claim_index=0,status="missing",reason="未提供引用")],
    ))
    markdown = render_markdown(case)
    assert "app.py:1-1" in markdown and "run()" in markdown
    assert "#source-s1" in markdown and 'id="source-s1"' in markdown
    assert "未提供引用" in markdown


@pytest.mark.parametrize("path", ["../outside.py", "/absolute.py", "C:\\secret.py"])
def test_source_paths_must_stay_inside_repository(path: str) -> None:
    with pytest.raises(ValueError):
        SourceExcerpt(id="s1",path=path,start_line=1,end_line=1,snippet="x")


def test_modified_git_snapshot_does_not_claim_a_clean_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reposleuth_toolkit.git_tool import _repo_revision

    (tmp_path / ".git").mkdir()

    def fake_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        output = " M app.py\n" if "status" in args else "a" * 40 + "\n"
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr("reposleuth_toolkit.git_tool._run_git", fake_git)
    assert _repo_revision(tmp_path) == ""


def test_full_graph_resolves_citations_and_ignores_forged_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reposleuth_orchestrator.graph import build_graph
    from reposleuth_orchestrator.state import CaseFile
    from reposleuth_report import render_markdown

    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "app.py").write_text('API_KEY = "synthetic-graph-sensitive-value"\n', encoding="utf-8")

    class Model:
        def invoke(self, prompt: str):
            assert "synthetic-graph-sensitive-value" not in prompt
            match = re.search(r"^\[(s\d+)\] app.py:", prompt, re.MULTILINE)
            assert match is not None
            request = {"claim_index":0,"source_ids":[match[1]]}
            if "Chief" in prompt:
                payload = {
                    "repo_name":"forged", "onboarding":["Read app.py"],
                    "risks":["app.py: literal credential", "Unsupported risk"],
                    "onboarding_citations":[request], "risk_citations":[request],
                    "degraded":True,
                    "risk_evidence":[{"claim_index":1,"status":"verified","sources":[]}],
                }
            else:
                payload = {"agent":"reader","score":7,"findings":["app.py: literal credential"],"citations":[request]}
            return SimpleNamespace(content=json.dumps(payload))

    final = build_graph(Model(), cache_dir=tmp_path / "cache").invoke({"repo_url":str(repo)})
    report = final["report"]
    assert report.repo_name == "demo" and report.degraded is False
    assert report.onboarding_evidence[0].status == "verified"
    assert [e.status for e in report.risk_evidence] == ["verified", "missing"]
    for role in ("cartographer", "reader", "auditor"):
        assert final[f"verdict_{role}"].evidence[0].status == "verified"
    markdown = render_markdown(CaseFile.model_validate(final))
    assert "app.py:1-1" in markdown and "[REDACTED]" in markdown
    assert "synthetic-graph-sensitive-value" not in markdown

    from fastapi.testclient import TestClient
    import reposleuth_web.server as server

    monkeypatch.setattr(server, "_build_llm", lambda model: Model())
    monkeypatch.setattr(server, "_default_model", lambda: "offline")
    monkeypatch.setattr(server, "_CACHE_DIR", tmp_path / "web_cache")
    with TestClient(server.app) as client:
        response = client.post("/api/investigate", json={"repo_url":str(repo)})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    web_report = next(event["report"] for event in events if event["type"] == "report")
    assert web_report["onboarding_evidence"][0]["status"] == "verified"
    assert web_report["risk_evidence"][1]["status"] == "missing"
    assert all(event["evidence"][0]["status"] == "verified" for event in events if event["type"] == "verdict")
    assert "synthetic-graph-sensitive-value" not in response.text


def test_model_cannot_cite_a_source_outside_its_prompt_budget(tmp_path: Path) -> None:
    from reposleuth_orchestrator.agents import make_reader
    from reposleuth_orchestrator.state import CaseFile

    for i in range(10):
        (tmp_path / f"file_{i}.py").write_text("VALUE = 1\n" * 500, encoding="utf-8")
    ingest = ingest_repo(tmp_path)
    hidden_id = ingest.sources[-1].id

    class Model:
        def invoke(self, prompt: str):
            assert f"[{hidden_id}] " not in prompt
            return SimpleNamespace(content=json.dumps({
                "agent":"reader", "score":7, "findings":["fabricated location"],
                "citations":[{"claim_index":0,"source_ids":[hidden_id]}],
            }))

    result = make_reader(Model())(CaseFile(ingest=ingest))["verdict_reader"]
    assert result.evidence[0].status == "invalid" and not result.evidence[0].sources


def test_degraded_onboarding_is_labeled_as_fallback() -> None:
    from reposleuth_orchestrator.agents import make_chief
    from reposleuth_orchestrator.state import CaseFile

    class Model:
        def invoke(self, prompt: str):
            return SimpleNamespace(content="invalid json")

    report = make_chief(Model())(CaseFile())["report"]
    assert report.degraded is True
    assert all(e.basis == "fallback" for e in report.onboarding_evidence)
