# Golden Repos 基准仓库

回归测试基准：不把第三方仓库代码提交到本仓库，测试运行时按需克隆到
临时目录（`git_tool.clone_repo` 自带体积预检）。

## 基准清单（v0.1）

| 仓库 | 用途 | 预期 |
|------|------|------|
| pallets/click | Python 中型仓库 | RepoMap 模块数 > 20，edges 连通，无 crash |
| httpie/cli | Python 中型仓库（含 CLI 入口） | RepoMap 正常；risk_scan 可跑通 |

## 用法

后续分支（investigation / scouting）的集成测试引用这里的仓库 URL；
feat/toolkit 的单测用 `tests/test_toolkit.py` 内构造的微型仓库即可，
无需网络。

## 回归口径

每个 golden repo 记录一次基线 JSON（模块数 / 边数 / 外部依赖数），
工具逻辑变更后 diff 基线：数字变化必须能被代码变更解释。
