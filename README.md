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

# 5b. Web Server（FastAPI + SSE 前端，浏览器直接调用 Agent）
python -m reposleuth_web.server
# 打开 http://127.0.0.1:8000 —— 输入模糊需求，
# 实时观看 检索→门控→三侦探 各阶段事件流，最终渲染 mermaid 报告，
# 置信度不足阈值时在页面上人工确认候选仓库。

# 6. MCP Server（供 Claude / Cursor 等调用）
python -m reposleuth_mcp
```

## 测试

```bash
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests -q
```

- 单测不依赖网络与真实 LLM（fake chat model + 本地样例仓库）
- golden repo 基线：`tests/golden_repos/baselines.json`（pallets/click、httpie/cli）

## 缓存与证据处理

- 默认缓存目录为 `<仓库名>-<来源指纹>`，不同来源的同名仓库分别保存；
  指纹旁文件用于验证来源，旧的未验证目录不会被直接复用。旧缓存保留，首次分析会创建新缓存。
- 显式指定缓存名称时，若已有目录的来源不符或无法验证，会报错并保留已有目录。
  普通本地目录的缓存需放在源目录之外；Git 获取超时为 120 秒。
- 仓库文本排除 `.env` 和 `.env.*` 内容，并遮蔽常见凭据赋值与 PEM 私钥后交给模型。
  风险扫描仍读取原始文件；规则脱敏不能识别任意格式或动态拼接的秘密。
- 三侦探证据包总预算为 20,000 字符，主笔为 6,000 字符；依赖图、风险和代码共同分配预算。
  截断处有标记，目录树也计入文本化总预算。

## 可追溯报告

- 工具层为脱敏源码生成片段 ID、相对路径和原始行号；模型通过 `citations` 引用实际收到的片段。
- 引用校验仅接受本轮预算内完整展示的片段。未知 ID、重复结论索引会标记为无效，缺失引用会明确显示。
  校验结果由程序回填，模型不能自行声明引用已验证；位置一致不代表结论语义已得到证明。
- Web 页面可展开代码证据；下载的 Markdown 含证据锚点与脱敏片段。
  GitHub 副本记录固定 commit 并生成源码链接；工作区有修改、版本无法确认或来源为普通目录时不生成提交链接。
- 原有 `findings`、`onboarding`、`risks` 字符串列表保持兼容，新引用信息通过附加字段输出。

## 分支与版本

| 分支 / tag | 内容 |
|-----------|------|
| `v0.2-pipeline` | 直连分析流水线（三侦探 + 主笔 + 报告） |
| `v0.3-cockpit` | Gradio 界面（候选确认 + mermaid 报告视图） |
| `v0.4-mcp` | MCP Server（5 个工具，可被任意 MCP Client 调用） |

## 设计说明

见 [AGENTS.md](AGENTS.md)：分层纪律、编码规范、Agent 开发规范、提交规范与环境踩坑记录。
