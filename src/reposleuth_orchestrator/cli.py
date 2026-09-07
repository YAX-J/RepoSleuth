"""RepoSleuth CLI：python -m reposleuth_orchestrator <repo_url> [options]

模型来源（优先级）：--model 参数 > REPOSLEUTH_MODEL 环境变量 > 报错提示。
真实模型需自行安装对应 provider 包（如 langchain-deepseek / langchain-dashscope）
并配置相应 API Key 环境变量。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from reposleuth_report import save_report
from reposleuth_toolkit import RepoTooLarge

from .graph import build_graph, build_scout_graph
from .scout import DEFAULT_THRESHOLD
from .state import CaseFile

ZHIPU_OPENAI_BASE = "https://open.bigmodel.cn/api/paas/v4/"


def _build_llm(model: str, provider: str = "", base_url: str = ""):
    """懒加载真实模型（仅 CLI 入口触发，保持库导入零 LLM 依赖）。

    - provider/base_url：--provider / --base-url 或环境变量 REPOSLEUTH_PROVIDER / REPOSLEUTH_BASE_URL；
    - glm 系列自动路由到智谱 OpenAI 兼容端点（凭据读 ZHIPUAI_API_KEY）；
    - 其余模型交给 init_chat_model 自行推断。
    """
    from langchain.chat_models import init_chat_model

    provider = provider or os.environ.get("REPOSLEUTH_PROVIDER", "")
    base_url = base_url or os.environ.get("REPOSLEUTH_BASE_URL", "")

    kwargs: dict = {}
    if not provider and model.startswith("glm"):
        provider = "openai"
        base_url = base_url or ZHIPU_OPENAI_BASE
    if provider:
        kwargs["model_provider"] = provider
    if base_url:
        kwargs["base_url"] = base_url
    if model.startswith("glm") and os.environ.get("ZHIPUAI_API_KEY"):
        kwargs["api_key"] = os.environ["ZHIPUAI_API_KEY"]
    if kwargs.get("model_provider") == "openai":
        # 结构化 JSON 输出容易被默认 max_tokens 截断，且评审需要确定性
        kwargs["max_tokens"] = 4096
        kwargs["temperature"] = 0
    return init_chat_model(model, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reposleuth",
        description="RepoSleuth：多智能体代码库分析（直连模式）",
    )
    # .env 优先从工作目录加载，找不到则回退到项目根目录
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser.add_argument("repo_url", help="GitHub URL 或本地仓库路径")
    parser.add_argument("--model", default=os.environ.get("REPOSLEUTH_MODEL", ""),
                        help="模型名（如 glm-4-flash / deepseek-chat / qwen-plus），默认读 REPOSLEUTH_MODEL")
    parser.add_argument("--provider", default="", help="模型 provider（默认按模型名推断）")
    parser.add_argument("--base-url", default="", help="OpenAI 兼容端点覆盖")
    parser.add_argument("--search", action="store_true",
                        help=" scouting 模式：把 repo_url 参数当作模糊需求，自动检索选仓")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help="置信度门控阈值（默认 7）")
    parser.add_argument("--cache-dir", default="repos_cache", help="克隆缓存目录")
    parser.add_argument("--out", default="reports", help="报告输出目录")
    args = parser.parse_args(argv)

    if not args.model:
        print("错误：未指定模型。用 --model 或设置 REPOSLEUTH_MODEL 环境变量。", file=sys.stderr)
        return 2

    try:
        llm = _build_llm(args.model, provider=args.provider, base_url=args.base_url)
    except Exception as exc:  # provider 包缺失 / key 未配置
        print(f"模型初始化失败：{exc}\n提示：安装对应 provider 包并配置 API Key 环境变量。", file=sys.stderr)
        return 2

    requirement = args.repo_url
    repo_url = args.repo_url

    if args.search:
        # ---------- scouting：模糊需求 → 检索选仓 ----------
        print(f"[scout] 需求理解中：{requirement}")
        scout_result = build_scout_graph(llm).invoke(CaseFile(requirement=requirement))
        if not isinstance(scout_result, CaseFile):
            scout_result = CaseFile.model_validate(scout_result)
        if not scout_result.candidates or not scout_result.ranked:
            print("未找到候选仓库，尝试换一组关键词。", file=sys.stderr)
            return 1

        top = scout_result.ranked[0]
        if top.relevance >= args.threshold:
            chosen = scout_result.candidates[top.index]
            print(f"[scout] 置信度 {top.relevance}/10 ≥ 阈值 {args.threshold}，自动直选："
                  f"{chosen.full_name}（{top.reason}）")
            repo_url = chosen.html_url
        else:
            shortlist = scout_result.ranked[:3]
            print("[scout] 置信度不足阈值，请确认候选：")
            for i, r in enumerate(shortlist, 1):
                c = scout_result.candidates[r.index]
                print(f"  {i}. {c.full_name}  ★{c.stars}  [{r.relevance}/10] {r.reason}")
                print(f"     {c.description[:80]}")
            pick = input("选择编号（默认 1）：").strip() or "1"
            try:
                idx = shortlist[int(pick) - 1].index
            except (ValueError, IndexError):
                print("无效编号。", file=sys.stderr)
                return 2
            repo_url = scout_result.candidates[idx].html_url

    # ---------- 侦探分析（直连/scouting 共用） ----------
    print(f"[1/4] 克隆并分析仓库：{repo_url}")
    graph = build_graph(llm, cache_dir=Path(args.cache_dir))
    try:
        result = graph.invoke(CaseFile(repo_url=repo_url, requirement=requirement if args.search else ""))
    except RepoTooLarge as exc:
        print(f"仓库超限：{exc}", file=sys.stderr)
        return 1
    final = result if isinstance(result, CaseFile) else CaseFile.model_validate(result)

    print("[2/4] 三侦探评审完成：", ", ".join(
        f"{a}={s}" for a, s in (final.report.scores or {}).items()
    ))
    print("[3/4] 渲染报告…")
    out_path = save_report(final, Path(args.out))

    print(f"[4/4] 完成 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
