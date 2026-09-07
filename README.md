# RepoSleuth

**Describe it. Sleuth finds it. You understand it.**
说个大概，替你读透。

多智能体代码库分析系统：输入模糊需求或仓库链接，Agent 自主检索 / 精读代码，
输出 **mermaid 架构图 + 新人上手路线 + 风险预警清单**。

## 架构

```
交互层    CLI（python -m reposleuth_orchestrator） / Gradio Cockpit / MCP Client
编排层    LangGraph 状态机（有状态）：需求理解 → 检索选仓 → 三侦探并行 → 主笔
工具层    MCP Server（无状态）：github_search / clone_repo / repo_map / risk_scan / ingest_repo
外部依赖  GitHub API · git · LLM Provider（glm-4-flash / deepseek-chat / qwen…）
```

- **确定性优先**：AST 依赖图、风险扫描、架构图渲染全部规则实现；LLM 只做归纳与生成
- **三侦探并行**：Cartographer（架构）/ Reader（可读性）/ Auditor（风险）各自结构化评分
- **置信度门控**：重排 Top1 ≥ 阈值自动直选，否则弹候选卡片由用户确认
- **混合预检**：克隆前后双重体积检查 + scouting 阶段体积预过滤，超限仓库不浪费 token

## 快速开始

```bash
# 1. 安装
python -m venv .venv && .venv/Scripts/pip install -e ".[orchestrator,web,dev]"
# 或按需: pip install -e ".[agent,mcp]"

# 2. 配置（复制模板并填入 Key）
cp .env.example .env    # 填 ZHIPUAI_API_KEY（glm-4-flash 免费）

# 3. 直连模式：分析任意仓库
python -m reposleuth_orchestrator https://github.com/pallets/click --model glm-4-flash

# 4. 模糊需求模式：Agent 自己找仓库
python -m reposleuth_orchestrator "找一个处理 PDF 的轻量 Python 库" --search --model glm-4-flash

# 5. Web 界面
python -m reposleuth_web

# 6. MCP Server（供 Claude / Cursor 等调用）
python -m reposleuth_mcp
```

## 测试

```bash
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests -q
```

- 单测不依赖网络与真实 LLM（fake chat model + 本地样例仓库）
- golden repo 基线：`tests/golden_repos/baselines.json`（pallets/click、httpie/cli）

## 分支与版本

| 分支 / tag | 内容 |
|-----------|------|
| `v0.2-pipeline` | 直连分析流水线（三侦探 + 主笔 + 报告） |
| `v0.3-cockpit` | Gradio 界面（候选确认 + mermaid 报告视图） |
| `v0.4-mcp` | MCP Server（5 个工具，可被任意 MCP Client 调用） |

## 设计说明

见 [AGENTS.md](AGENTS.md)：分层纪律、编码规范、Agent 开发规范、提交规范与环境踩坑记录。
