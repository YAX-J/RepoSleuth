# RepoSleuth — 简历素材与亮点提炼

> 用途：把 RepoSleuth 项目写成简历条目 / 面试讲述材料。
> 提炼原则：只保留简历里有"区分度"的工程亮点，附"体现了什么能力"，方便按需裁剪。

---

## 一、一句话定位（建议放在简历项目名下方）

**多智能体代码库分析系统**：输入模糊需求或仓库链接，Agent 自主检索 / 精读代码，输出 Mermaid 架构图 + 新人上手路线 + 风险预警清单。

---

## 二、技术栈

Python 3.11+ · LangGraph / LangChain · Pydantic v2 · FastAPI + SSE · Gradio · MCP（Model Context Protocol）· GitHub Search API · semgrep · GLM-4-Flash / DeepSeek / Qwen（OpenAI 兼容端点）

---

## 三、项目描述（可直接贴简历）

RepoSleuth 是基于 LLM 的多智能体代码库分析平台。用户输入模糊需求（如"找一个处理 PDF 的轻量 Python 库"）或任意仓库链接，系统通过**需求理解 → 多路检索 → 置信度门控**自主定位目标仓库，再调度三个角色化侦探 Agent（架构 / 可读性 / 安全）**并行**分析，最后由主笔 Agent 汇总生成含架构图、上手路线与风险清单的结构化报告。提供 **CLI、Gradio Cockpit、FastAPI SSE Web、MCP Server** 四种接入形态，可被 Claude / Cursor 等直接调用。

---

## 三之一、项目亮点（简历可直接贴的差异化卖点）

> 与 JD 对齐、可直接抄进简历的项目亮点清单，强调"别人项目少有、你能讲清楚"的差异化能力。

- **确定性优先架构**：依赖图、风险扫描、架构图渲染全部用 AST + 正则规则实现，**零 LLM 参与**——LLM 仅做归纳生成，成本可控、可单测、可复现（这是多数 LLM 项目欠缺的工程意识）。
- **多智能体编排**：LangGraph 状态机驱动架构/可读性/安全三侦探**并行**分析 + 主笔汇总，落地 **Multi-Agent 协作、任务规划与状态管理**；以**置信度门控**实现 Human-in-the-loop（自动选仓或交人工确认）。
- **模型无关 + 鲁棒容错**：GLM-4 / DeepSeek / Qwen 统一接入（参数调优 + 异常兜底）；结构化输出经 **pydantic 校验 + 重试 + 确定性降级**，工程化应对模型幻觉与输出不稳定。
- **前沿工具链集成**：将克隆 / 依赖图 / 风险扫描封装为 **Tool Use 并暴露为 MCP Server**，可被 Claude / Cursor 调用；基于 **FastAPI + SSE** 实现流式事件推送与实时可视化。
- **工程化交付**：分层架构（toolkit / orchestrator / web 严格分离）、Pydantic 唯一契约；单测**不依赖网络与真实 LLM**（fake model + 本地样例仓库）+ golden repo 回归；已对 pallets/click 等真实仓库**端到端验证**并发布 v0.2–v0.4 三版。

---

## 四、核心亮点（按简历价值排序，每条可独立成 bullet）

### 1. 确定性优先（Determinism-First）的工程哲学
- 架构图、依赖图、风险扫描全部用规则 / AST / 正则实现，**零 LLM 参与**；LLM 只负责归纳与生成。
- 依赖图：仅用标准库 `ast` + `sys.stdlib_module_names` 解析 Python 导入边，无 pydeps / graphviz 等外部依赖（Windows 零安装、可单测、完全确定）。
- 风险扫描：内置正则规则库（硬编码凭据 / 私钥 / SQL 拼接 / eval·exec / shell=True），含占位符排除逻辑**主动降误报**，semgrep 可作为可选增强并优雅回退。
- **体现能力**：成本与可靠性意识、对"何时该用 LLM / 何时用规则"的判断力——这是 LLM 应用工程里很加分的一点。

### 2. LangGraph 多智能体状态机编排
- 直连模式流水线：`acquire → survey → {cartographer, reader, auditor 并行} → chief → END`。
- 三侦探 Agent **并行执行**，每个写各自独立的状态字段（`verdict_*`），规避并行节点写同一键互相覆盖。
- 侦察模式（模糊需求）：`plan(LLM 生成搜索词) → search(多路去重+体积预过滤) → rank(LLM 重排) → gate(置信度门控)`。
- **体现能力**：真正落地过多 Agent 协作与状态编排，而非只调一次 ChatCompletions。

### 3. 置信度门控（Confidence Gating）的自主决策
- Top1 相关度 ≥ 阈值（默认 7）→ 自动直选；否则返回候选短名单交由用户确认，避免"幻觉式"盲选。
- 检索阶段即做体积预过滤，防止门控选中的超大仓库在克隆预检被拒、整条流水线空跑。
- **体现能力**：把"人在回路（HITL）"设计进系统，权衡了自动化与可控性。

### 4. 结构化输出 + 校验 + 重试 + 降级（鲁棒性）
- LLM 输出 JSON → 容忍代码围栏/前后缀提取 → `pydantic` 校验 → 失败带纠偏提示重试 → 主笔失败走**确定性兜底报告**（不静默吞错）。
- LLM 调用统一走 `init_chat_model` 风格工厂，模型名/温度读配置，**任意 BaseChatModel 可注入**（测试用 fake model 冒烟）。
- **体现能力**：生产级容错设计，区别于 demo 级代码。

### 5. 模型无关的多 LLM 接入
- 同一套编排兼容 GLM-4-Flash / DeepSeek / Qwen，经 Zhipu OpenAI 兼容端点打通；配置从 `.env` 加载。
- **体现能力**：供应商解耦，不被单一模型绑定。

### 6. Token / 成本预算控制
- 仓库文本化 `ingest_repo` 带字符预算（总量 20w、单文件 8k），超大文件截断、预算耗尽记入 `truncated_files`；喂给 LLM 的证据包统一在 2w 字符内截断。
- **体现能力**：LLM 应用的真实成本意识，面试常被追问。

### 7. 四种接入形态，现代 AI 工具链集成
- **MCP Server**（stdio）：把 5 个无状态工具（github_search / clone_repo / repo_map / risk_scan / ingest_repo）暴露为 MCP，可被 Claude / Cursor 调用——踩在 AI 工具协议前沿。
- **FastAPI + SSE Web**：后端只做"图驱动 + 事件转发"零业务逻辑，前端实时观看 检索→门控→三侦探 各阶段事件流并渲染 Mermaid 报告。

### 8. 工程纪律与可测试性
- 分层契约：toolkit 不依赖 LLM、orchestrator 不直接碰文件系统；跨模块数据一律 Pydantic v2 模型（唯一"案卷"契约），禁裸 dict。
- 单测**不依赖网络与真实 LLM**：本地构造特征齐全的样例仓库 + fake chat model 冒烟；golden repo 回归（pallets/click、httpie/cli）基线指标（模块数/边数/外部依赖数）变化须能被代码变更解释。
- Conventional Commits + 分支模型（feat/* → main 打 tag），已发布 `v0.2-pipeline` / `v0.3-cockpit` / `v0.4-mcp` 三版。

---

## 五、简历精简版（针对你提供的 4 份 JD 截图再优化）

> 你给的 4 份 JD 共性关键词：**AI Coding 工具（Cursor/Claude Code）/ Agent 全机制（上下文·规划·工具调用·状态·记忆·执行控制·RAG·结果验证）/ MCP / Multi-Agent / LangGraph / 流式输出 / 不确定性处理 / 幻觉与 Prompt 注入风险 / 全栈跨端 / GitHub 开源项目 / ToB 工程化交付**。以下版本按这些关键词重写，更适合应届/初级 AI 应用/Agent/全栈岗。

- **RepoSleuth｜多智能体代码库分析系统（Python 3.11 / LangGraph / FastAPI）**
  - 覆盖 Agent 全链路机制：基于 **LangGraph** 实现任务规划（scout 需求理解 + 搜索词生成）、上下文构建（仓库文本化 + 证据包预算控制）、**Tool Use**（克隆 / 依赖图 / 风险扫描封装为 Agent 可调用的工具）、状态管理（`CaseFile` 状态契约 + 并行节点独立字段）、执行控制与结果验证（pydantic 结构化校验 + 重试 + 降级兜底）。
  - **AI Coding 工具重度使用**：借助 Cursor / Claude Code / CodeBuddy 完成需求分析、代码生成、测试补全与文档沉淀；将不确定性处理工程化——LLM 仅负责归纳生成，架构图、依赖图、风险扫描用 AST/规则确定性实现，并通过结构化输出 + 重试 + 确定性降级应对模型幻觉与输出不稳定。
  - **全栈工程化交付**：后端 FastAPI + SSE 流式推送，前端实时可视化多 Agent 流水线；提供 CLI / Gradio / Web / **MCP Server** 四种接入，可被 Claude / Cursor 调用；单测不依赖网络与真实 LLM（fake model + 本地样例仓库），golden repo 回归；已对 pallets/click 等真实仓库端到端验证，发布 v0.2–v0.4 三版，代码开源在 GitHub 可供 review。
  - **项目亮点（差异化卖点）**：
    - **确定性优先**：依赖图 / 风险扫描 / 架构图渲染全部用 AST + 正则规则实现，零 LLM 参与——成本可控、可单测、可复现，是多数 LLM 项目欠缺的工程意识；
    - **多智能体编排**：LangGraph 状态机驱动三侦探并行分析 + 主笔汇总，置信度门控实现 Human-in-the-loop（自动选仓或交人工确认）；
    - **模型无关 + 鲁棒容错**：GLM-4 / DeepSeek / Qwen 统一接入；结构化输出经 pydantic 校验 + 重试 + 确定性降级，工程化应对模型幻觉与输出不稳定；
    - **前沿工具链集成**：将克隆 / 依赖图 / 风险扫描封装为 Tool Use 并暴露为 MCP Server，可被 Claude / Cursor 调用；
    - **工程化交付**：分层架构（toolkit / orchestrator / web 严格分离）、Pydantic 唯一契约；单测零网络 / 零真实 LLM + golden repo 回归，真实仓库端到端验证并发布三版。

### 五之一、这 4 份 JD 的高频要求 × 项目对应点

| JD 要求（按出现频次排序） | 项目对应实现 | 代码位置 / 证据 |
|---|---|---|
| AI Coding 工具（Cursor/Claude Code） | 本项目即使用 AI Coding 工具迭代开发 | 交付文档、git log、代码结构 |
| Agent 全机制：上下文构建、任务规划、工具调用、状态管理、记忆、执行控制、RAG、结果验证 | 上下文：`ingest_repo` + `_evidence()` 预算打包；任务规划：`scout_query` 生成搜索词；Tool Use：toolkit 工具 + MCP；状态管理：`CaseFile`；记忆：LangGraph 状态；执行控制：重试/降级；结果验证：pydantic 校验 | `ingest_tool.py`、`agents.py`、`mcp/server.py`、`state.py` |
| MCP / Multi-Agent | stdio MCP Server 暴露 5 工具；三侦探并行 + 主笔汇总 | `mcp/server.py`、`graph.py` |
| LangGraph / LangChain | 状态机编排，三侦探并行 | `graph.py`、`state.py` |
| 流式输出 / Streaming | FastAPI SSE 逐节点推送 | `web/server.py` |
| 模型不确定性 / 幻觉 / Prompt 注入风险 | 确定性优先 + 结构化输出校验 + 重试 + 降级；风险扫描含 Prompt 注入类模式 | `agents.py`、`_degraded_report`、`risk_tool.py` |
| 全栈 / 跨端工程基础 | FastAPI 后端 + 前端可视化 + CLI + Gradio | `web/server.py`、`app.py` |
| GitHub / 开源项目 | 项目本身开源在 GitHub（如已开源则填链接；如未开源建议尽快整理公开） | GitHub 仓库链接 |
| ToB / 工程化交付 | 分层架构、Pydantic 契约、单测、golden repo 回归、版本 tag | `tests/`、git tags |
| 质量意识 / 测试评估 | fake model 冒烟、golden repo 基线、Conventional Commits | `tests/`、git log |

> 诚实提示：JD 中提到的 **RAG（向量库）/ SFT / vLLM / KV Cache / 推理加速** 本项目未深入。面试若被问起，建议表述为"具备 RAG 上下文工程与检索实践，但向量库与微调仍在学习计划中"，不要过度包装。

### 五之二、4 份 JD 的匹配度排序
1. **AI Agent 开发工程师（图 2）**：匹配度最高，所有关键词几乎全中。
2. **AI 应用研发工程师 / AI Coding 方向（图 3）**：匹配度高，重点突出 AI Coding 工具使用与生产级代码交付。
3. **AI 全栈开发工程师（图 4）**：匹配度中高，突出全栈交付与 AI 工作流编排。
4. **银泰星 AI 科技（图 1）**：匹配度中等偏上，偏 ToB/工程化/业务理解，可弱化 Agent 深度、强调工程化交付与真实仓库验证。

---

## 六、面试可能被追问 + 建议准备

| 追问点 | 建议讲法 |
|--------|----------|
| 为什么不直接让 LLM 画图？ | 架构图由依赖图数据确定性渲染，避免 LLM 编造不存在的模块/边；可复现、可单测、零 token 成本。 |
| 并行 Agent 怎么避免冲突？ | CaseFile 状态契约里三侦探各写独立字段（verdict_cartographer/reader/auditor），LangGraph 并行节点无写竞争。 |
| 门控阈值怎么定的？ | 默认 7/10，作为自动化与人工确认的分界；本质是"置信度不足就交还控制权"的 HITL 设计。 |
| 风险扫描误报怎么处理？ | 保守规则 + 占位符（your_key/example/${VAR}）排除，宁可漏报不误报；定位是给 Agent 提供线索而非替代 SAST。 |
| 测试为何不连真实 LLM？ | 用 fake chat model 冒烟 + 本地样例仓库，保证 CI 快、稳、免费；golden repo 回归防回归。 |

---

## 七、可量化的"成绩"话术（简历里用，需你按实际补充数字）

- 已支撑 N 个仓库的自动分析与上手引导；
- 工具层单测覆盖 clone / repo-map / risk-scan / ingest 四条主链路，CI 零网络依赖；
- 单仓库分析 LLM 证据包控制在 2w 字符内，显著降低 token 开销；
- 发布 3 个版本（pipeline / cockpit / mcp），均通过 golden repo 回归。

---

## 八、BOSS 直聘招呼用语（按你发的 4 份 JD 定制）

> BOSS 直聘打招呼有字数限制（约 100-150 字），建议控制在 3-4 行。下方每段都把"岗位名"标为 `【】`，发送前替换即可。

### 1. 通用版（4 个岗位都能发）

```
您好，我对贵司的【岗位名】很感兴趣。我是 2027 届计算机/AI 相关专业应届生，独立完成了基于 LangGraph 的多智能体项目 RepoSleuth，覆盖任务规划、Tool Use、MCP 接入、FastAPI+SSE 流式输出与结构化输出校验降级，已对真实仓库端到端验证。方便发您简历和项目链接吗？
```

### 2. AI Agent 开发工程师（图 2，最匹配）

```
您好，看到贵司 AI Agent 开发工程师岗位与我的项目经历高度匹配。我独立完成的 RepoSleuth 用 LangGraph 编排多 Agent（架构/可读性/安全并行分析），并封装为 MCP Server，覆盖上下文构建、任务规划、Tool Use、状态管理、执行控制与结果验证。方便发您简历和 GitHub 链接吗？
```

### 3. AI 应用研发工程师 / AI Coding 方向（图 3）

```
您好，我对贵司 AI 应用研发工程师岗位很感兴趣。我平时重度使用 Cursor / Claude Code / CodeBuddy 辅助开发，独立项目 RepoSleuth 基于 LangGraph + FastAPI + SSE 实现多 Agent 代码分析、MCP 工具暴露、结构化输出降级，工程化分层与单测完整。期待把简历发您看看～
```

### 4. AI 全栈开发工程师（图 4）

```
您好，我对贵司 AI 全栈开发工程师岗位很感兴趣。我独立完成的 RepoSleuth 覆盖前后端全链路：LangGraph 多 Agent 编排 + FastAPI 流式后端 + 前端实时可视化，提供 CLI/Gradio/Web/MCP 四种接入，已在真实仓库端到端验证并发布 3 个版本。方便发您简历吗？
```

### 5. 银泰星 AI 科技（图 1，偏 ToB/工程化）

```
您好，我对贵司 AI 科技方向很感兴趣。我独立完成的 RepoSleuth 是一个面向代码库理解的 AI 应用项目，用 Python + FastAPI + LangGraph 实现多 Agent 协作，后端分层清晰、带完整单测与真实仓库验证，比较贴近 ToB 工程化交付。方便发您简历吗？
```

### 6. 已读未回 / 跟进版

```
您好，打扰了。之前关注到贵司【岗位名】，我的 RepoSleuth 项目正好覆盖了 JD 里提到的 LangGraph 多智能体、MCP、Tool Use 与流式输出，GitHub 已开源。如果方便，希望能有一次沟通机会，谢谢！
```

> **发送前注意**：
> - 把 `2027 届` / `计算机/AI` 换成你的真实届数和专业；
> - 如果 RepoSleuth 还没开源，把"GitHub 已开源"改成"可展示的项目 Demo/文档"；
> - 建议优先发**图 2（AI Agent）**和**图 3（AI Coding）**，匹配度最高；图 1 银泰可适当强调工程化与 ToB 交付经验。
