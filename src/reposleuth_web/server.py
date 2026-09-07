"""RepoSleuth Web Server：FastAPI + SSE，把编排图暴露给自定义前端。

设计原则（遵循 AGENTS.md 确定性优先）：
- 后端只做"图驱动 + 事件转发"，不做任何分析逻辑；
- 所有分析仍由 orchestrator 的 LangGraph 状态机完成，本文件零业务逻辑；
- 事件协议（SSE，data: <json>\n\n）：
  scout:        stage / queries / candidates / ranked / gate / error
  investigate:  stage / acquire / survey / verdict / report / error
  公共结束事件:  done
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from reposleuth_orchestrator import build_graph, build_scout_graph
from reposleuth_orchestrator.cli import _build_llm
from reposleuth_orchestrator.scout import DEFAULT_THRESHOLD
from reposleuth_orchestrator.state import CaseFile
from reposleuth_report import render_markdown
from reposleuth_toolkit import RepoTooLarge

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_STATIC_DIR = Path(__file__).parent / "static"
_CACHE_DIR = Path(os.environ.get("REPOSLEUTH_CACHE_DIR", "repos_cache"))

app = FastAPI(title="RepoSleuth", version="0.4.0")


class ScoutRequest(BaseModel):
    requirement: str = Field(min_length=2, max_length=500)
    model: str = ""
    threshold: int = Field(default=DEFAULT_THRESHOLD, ge=1, le=10)


class InvestigateRequest(BaseModel):
    repo_url: str = Field(min_length=4)
    model: str = ""


def _sse(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _default_model() -> str:
    return os.environ.get("REPOSLEUTH_MODEL", "")


def _dump(obj: Any) -> Any:
    """pydantic 模型 / dict 混合输出的统一序列化。"""
    return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj


def _candidate_view(c: Any) -> dict:
    d = _dump(c)
    return {
        "full_name": d["full_name"],
        "html_url": d["html_url"],
        "description": d.get("description", ""),
        "stars": d.get("stars", 0),
        "language": d.get("language", ""),
        "size_kb": d.get("size_kb", 0),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/config")
def config() -> dict:
    return {"model": _default_model(), "threshold": DEFAULT_THRESHOLD}


@app.post("/api/scout")
def scout(req: ScoutRequest) -> StreamingResponse:
    """模糊需求 → 检索 → 重排 → 门控。SSE 逐节点推送。"""

    def events() -> Iterator[str]:
        try:
            model = req.model or _default_model()
            if not model:
                yield _sse({"type": "error", "message": "未配置模型：请在 .env 设置 REPOSLEUTH_MODEL"})
                return
            llm = _build_llm(model)
        except Exception as exc:
            yield _sse({"type": "error", "message": f"模型初始化失败：{exc}"})
            return

        state: dict[str, Any] = {"requirement": req.requirement}
        yield _sse({"type": "stage", "node": "plan", "label": "需求解析中"})

        try:
            for chunk in build_scout_graph(llm).stream(state, stream_mode="updates"):
                for node, delta in chunk.items():
                    state.update(delta)
                    if node == "plan":
                        yield _sse({"type": "queries", "queries": delta.get("queries", [])})
                    elif node == "search":
                        items = [_candidate_view(c) for c in delta.get("candidates", [])]
                        yield _sse({"type": "candidates", "items": items, "total": len(items)})
                    elif node == "rank":
                        ranked = delta.get("ranked", [])
                        views = []
                        for r in ranked:
                            cands = state.get("candidates") or []
                            cand = cands[r.index] if 0 <= r.index < len(cands) else None
                            view = _candidate_view(cand) if cand else {}
                            view.update({"relevance": r.relevance, "reason": r.reason})
                            views.append(view)
                        yield _sse({"type": "ranked", "items": views})
                        top = ranked[0] if ranked else None
                        if not top:
                            yield _sse({"type": "gate", "mode": "empty",
                                        "threshold": req.threshold,
                                        "message": "未找到候选仓库，换个说法试试"})
                        elif top.relevance >= req.threshold:
                            chosen = state["candidates"][top.index]
                            yield _sse({"type": "gate", "mode": "auto",
                                        "threshold": req.threshold,
                                        "top_relevance": top.relevance,
                                        "repo_url": chosen.html_url,
                                        "full_name": chosen.full_name,
                                        "reason": top.reason})
                        else:
                            yield _sse({"type": "gate", "mode": "confirm",
                                        "threshold": req.threshold,
                                        "top_relevance": top.relevance,
                                        "shortlist": views[:3]})
        except Exception as exc:
            yield _sse({"type": "error", "message": f"侦察失败：{exc}"})
        yield _sse({"type": "done"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/investigate")
def investigate(req: InvestigateRequest) -> StreamingResponse:
    """选定仓库 → 三侦探分析 → 首席报告。SSE 逐节点推送。"""

    def events() -> Iterator[str]:
        try:
            model = req.model or _default_model()
            if not model:
                yield _sse({"type": "error", "message": "未配置模型：请在 .env 设置 REPOSLEUTH_MODEL"})
                return
            llm = _build_llm(model)
        except Exception as exc:
            yield _sse({"type": "error", "message": f"模型初始化失败：{exc}"})
            return

        state: dict[str, Any] = {"repo_url": req.repo_url}
        try:
            for chunk in build_graph(llm, cache_dir=_CACHE_DIR).stream(state, stream_mode="updates"):
                for node, delta in chunk.items():
                    state.update(delta)
                    if node == "acquire":
                        repo = delta.get("repo")
                        view = _dump(repo) if repo else {}
                        yield _sse({"type": "acquire", "repo": {
                            "name": view.get("name", ""),
                            "file_count": view.get("file_count", 0),
                            "total_size_mb": round(view.get("total_size_bytes", 0) / 1024 / 1024, 1),
                            "local_path": view.get("local_path", ""),
                        }})
                    elif node == "survey":
                        rm = delta.get("repo_map")
                        stats = rm.stats if rm is not None else {}
                        rr = delta.get("risk_report")
                        yield _sse({"type": "survey", "stats": stats,
                                    "risk_summary": rr.summary() if rr is not None else {},
                                    "risk_engine": rr.engine if rr is not None else ""})
                    elif node in ("cartographer", "reader", "auditor"):
                        v = delta.get(f"verdict_{node}")
                        if v is not None:
                            d = _dump(v)
                            yield _sse({"type": "verdict", "agent": node, "score": d["score"],
                                        "findings": d.get("findings", []), "notes": d.get("notes", "")})
                    elif node == "chief":
                        case = CaseFile.model_validate(state)
                        report = case.report
                        if report is None:
                            yield _sse({"type": "error", "message": "案卷缺少 report（chief 未产出）"})
                        else:
                            yield _sse({"type": "report", "report": {
                                "repo_name": report.repo_name,
                                "mermaid": report.mermaid,
                                "onboarding": report.onboarding,
                                "risks": report.risks,
                                "scores": report.scores,
                                "degraded": report.degraded,
                                "markdown": render_markdown(case),
                                "stats": case.repo_map.stats if case.repo_map else {},
                            }})
        except RepoTooLarge as exc:
            yield _sse({"type": "error", "message": f"仓库超限：{exc}"})
        except Exception as exc:
            yield _sse({"type": "error", "message": f"分析失败：{exc}"})
        yield _sse({"type": "done"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def main() -> None:  # python -m reposleuth_web.server
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("REPOSLEUTH_PORT", "8000")))


if __name__ == "__main__":
    main()
