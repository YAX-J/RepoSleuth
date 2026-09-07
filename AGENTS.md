# AGENTS.md — RepoSleuth 开发与协作规范

> 本文件是 AI 助手与人类协作者共同遵守的项目宪法。写代码 / 提交前必读。
> 违反第 5、6 节的操作一律先停下来说明理由。

## 1. 项目概览与分层

一句话：多智能体代码库分析系统——模糊需求 → 自主检索仓库 → 三侦探 Agent 分析 → 输出 mermaid 架构图 / 上手路线 / 风险清单。

| 层 | 位置 | 职责 | 禁止事项 |
|----|------|------|---------|
| toolkit | `src/reposleuth_toolkit/` | 无状态工具：克隆预检 / AST 依赖图 / 风险扫描 / 文本化 | 依赖 LLM、持有全局状态 |
| orchestrator | `src/reposleuth_orchestrator/` | LangGraph 状态机、四类 Agent、置信度门控 | 绕过 toolkit 直接操作文件系统 |
| report | `src/reposleuth_report/`（规划） | mermaid / Markdown 报告渲染 | 写业务逻辑 |
| web | `src/reposleuth_web/`（可选） | Gradio / FastAPI 界面 | 同上 |

改任何代码前，先确认自己改的是哪一层；跨层职责互相渗透 = 设计错误。

## 2. 编码规范（Python）

1. Python >= 3.11；公共函数签名**必须**带类型注解
2. 标准库优先；新增第三方依赖必须写入 `pyproject.toml` 对应 extra，禁止不入册的裸装
3. 跨模块数据一律用 pydantic v2 模型（`models.py` 是唯一"案卷"契约），禁止裸 dict 传递
4. docstring 用中文，写清职责与边界；公共 API 必有 docstring
5. 命名：模块/函数 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE`；Agent 角色名用英文（Cartographer / Reader / Auditor / Scout / Chief）
6. 异常：toolkit 层自定义异常（如 `RepoTooLarge`），禁止裸 `except: pass`
7. 路径一律 `pathlib`；子进程调用必须 `capture_output=True` + `timeout`
8. **确定性优先**：能用规则 / AST / 正则解决的不用 LLM；LLM 只负责归纳与生成
9. toolkit 层禁止 import langchain（`langchain_tools.py` 除外，且须 try/except ImportError 优雅降级）

## 3. Agent 开发规范

1. **契约先行**：先定工具与 Agent 的输入/输出 Pydantic 模型，再写实现
2. prompt 一律放 `orchestrator/prompts/` 下的独立文件（版本化），禁止硬编码在 Python 逻辑里
3. Agent 输出必须结构化并经 pydantic 校验；校验失败走重试 / 降级路径，不允许静默吞掉
4. 有状态编排（迭代检索、置信度门控、多 Agent 评分合成）**只放编排层**；MCP 只封装无状态工具
5. 所有喂给 LLM 的文本必须过 token / 字符预算控制（参照 `ingest_tool` 的截断设计）
6. LLM 调用统一走 `init_chat_model` 风格的工厂，模型名/温度从配置读取，禁止散落硬编码

## 4. 测试规范

- 框架 pytest；**单测禁止依赖网络与真实 LLM**（本地构造样例仓库，参照 `tests/test_toolkit.py`；LLM 逻辑用 fake chat model 冒烟）
- golden repo 回归：`pallets/click`、`httpie/cli`；基线指标（模块数 / 边数 / 外部依赖数）变化必须能被代码变更解释
- 运行方式：`PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests -q`
- 新功能必须带验收测试；修 bug 必须先写复现测试再修
- 每条 feat 分支的"验收标准"以任务清单为准：测试通过 + golden 回归 + 人工 demo

## 5. Git 与提交规范

- **分支模型**：`main` 唯一稳定主干；功能串行开发 `feat/<name>`，验收后合回 `main` 并打 tag（`v0.x-<name>`）；禁止在 main 上直接开发
- **Commit message**：Conventional Commits（英文），格式 `<type>(<scope>): <subject>`
  - type：`feat` / `fix` / `chore` / `test` / `docs` / `refactor`
  - scope：`toolkit` / `orchestrator` / `report` / `web` / `mcp` / `repo`
  - 一个 commit 一个主题，禁止大杂烩；subject 用祈使句、不加句号
- **授权边界**：AI 可在用户确认后执行 commit；push 必须用户单独确认；禁止 force push、禁止改写已推送历史
- **高风险操作**（`reset --hard`、分支重建、历史改写）：先只读分析 + 列出受影响对象 + 显式确认后才能执行

## 6. 环境注意事项（本项目实测踩坑，务必遵守）

1. 本项目目录存在**文件写入回滚**现象：git 操作务必单条短命令，每次提交后必须验证（`git log` + `git status`）
2. 正常 `git commit` 的引用更新可能不落盘；兜底路径：`git write-tree` → `git commit-tree` → 手写 refs 文件（对象库写入始终可靠）
3. 访问 GitHub 需 `-c http.sslVerify=false`（代理吊销检查失败）
4. fetch 协商被损坏对象卡住时：先把本地 main 指回完好的旧提交再 fetch
5. 运行测试用 `PYTHONPATH=src` + 项目 `.venv`；`pip install -e .` 可能被中断，用依赖直装替代
6. 关键文件修改后**读回验证**；Edit 工具偶发"报告成功实际未写入"
7. **密钥一律放 `.env`**（已被 gitignore，模板见 `.env.example`），禁止把 Key 写进代码、测试或提交；CLI 启动时经 `load_dotenv` 自动加载

## 7. 协作节奏

- 结论先行 → 方案确认 → 实现 → 运行时验证（pytest / 构建）的循环推进
- 每阶段产出先给最小可验证版本，再按反馈小步迭代
- 语义有分歧时（命名、契约、边界）先对齐再动手，不赌猜测
