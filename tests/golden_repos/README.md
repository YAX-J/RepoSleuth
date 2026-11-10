# Golden Repos 基准仓库

回归测试基准：不把第三方仓库代码提交到本仓库。测试仅读取预先准备的本地副本，
不会自动克隆或访问网络。

## 基准清单（v0.1）

| 仓库 | 用途 | 预期 |
|------|------|------|
| pallets/click | Python 中型仓库 | RepoMap 模块数 > 20，edges 连通，无 crash |
| httpie/cli | Python 中型仓库（含 CLI 入口） | RepoMap 正常；risk_scan 可跑通 |

## 用法

在 `repos_cache/click` 和 `repos_cache/cli` 中准备 `baselines.json` 记录的固定 commit；
也可用 `REPOSLEUTH_GOLDEN_ROOT` 指定包含 `click/`、`cli/` 的本地目录。
新的默认分析缓存使用来源指纹后缀，不会自动成为 golden 副本。

执行 `PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_golden_repos.py -q -rs`。
仓库不存在或版本不同会明确跳过；正确版本的静态指标不匹配则失败。
`verdict_scores` 保留历史模型评分，仅作记录，不参与离线回归断言。

## 回归口径

每个 golden repo 记录一次基线 JSON（模块数 / 边数 / 外部依赖数），
工具逻辑变更后 diff 基线：数字变化必须能被代码变更解释。

## 2026-11-10 基础修复后的基线变化

| 仓库 | 模块数 | 内部边 | 外部依赖 | 总行数 |
|------|--------|--------|----------|--------|
| pallets/click | 90 → 90 | 196 → 163 | 7 → 6 | 29121 → 29121 |
| httpie/cli | 132 → 132 | 592 → 378 | 20 → 20 | 18988 → 18988 |

原因：`src/` 布局去除源码根前缀；`__init__.py` 的相对导入从包自身解析；
`from module import symbol` 归到真实模块并合并重复模块边，不再将函数/类当作模块。
原 click 有 190 条边、httpie 有 388 条边指向不存在的模块，修复后均为 0；
click 自身也不再被列为外部依赖。模块数和总行数均未变化。
