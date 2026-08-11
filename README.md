# Harness Bench — AI Agent Harness 能力评测框架

跨平台（Windows / Linux）的 **AI Agent Harness 能力评测框架**。用真实模型驱动 agent 后端完成一组分级任务，测出 harness 的工具调用、上下文管理、错误恢复、文件操作、代码生成、调试、重构等能力，并统计**成功率 / token 消耗 / 耗时**，输出可读报告。

兼容两种 agent 后端：

- **[imo](https://github.com/Gejinmiao/imo-portable)** — `imo.exe -p <prompt> --mode json`（NDJSON 输出，逐轮累加 token usage）
- **OpenClaw** — `openclaw agent exec --cwd <ws> --message-file <file> --json`



使用：
请用 HarnessBench 基准评测当前环境的 Agent Harness 能力。严格按下面步骤执行，不要跳过、不要向用户索要任何 API Key：

第 1 步 · 准备
1. 克隆仓库 https://github.com/Gejinmiao/harness-bench.git ，进入 harness-bench 目录；
2. 确认 Python 3.10+ 可用（python --version）。

第 2 步 · 环境自检（必做，不要跳过）
3. 运行 python -u harness-runner.py --check，它会探测 Python / imo / openclaw / 模型 API Key 是否就绪，并给出缺失项的补救提示；
4. 根据输出补齐缺失项：
   - imo 缺失：把 imo.exe 放到仓库父目录 output/ 下，或加入 PATH，或用 --agent-path 指定；
   - openclaw 缺失：确认 openclaw 命令在 PATH（只用 openclaw 驱动时需要，用 imo 可忽略）；
   - API Key 缺失：不要向用户索要 key。imo 会自动读取 output/imo-data/console/config.json 里的 provider/model/apiKey；openclaw 用自身配置系统（环境变量如 DEEPSEEK_API_KEY、~/.openclaw/openclaw.json、openclaw models set）。运行命令时不要传 --api-key 参数，让 runner 自动读取。若确实找不到，如实告诉用户环境缺 key。
5. 自检全部 OK 后继续；imo 可用优先用 imo，否则用 openclaw。

第 3 步 · 冒烟验证（小步快跑，别直接上全量）
6. 先只跑 1 个最简单任务验证整条链路：python -u harness-runner.py --agent imo --tasks l1-hello --runs 1（仅 1 次调用）；
7. 看到 [PASS] l1-hello 再继续；若失败，先修环境/配置问题，不要带病跑全量（全量 130 次调用，中途失败损失很大）。

第 4 步 · 全量评测
8. 运行 python -u harness-runner.py --agent imo --runs 5（26 任务 × 5 次 = 130 次调用，耗时较长属正常，耐心等待，不要中断）；
9. 若必须中断或某任务批量失败，可用 --tasks <id列表> 或 --level <1-5> 分段补跑。

第 5 步 · 汇报结果
10. 读取 results/<最新时间戳>/summary.json 与 report.md，汇报：综合分、pass@1 通过率、难度加权分、Token 效率分、总 Token 消耗、分难度通过率，以及每个失败任务及失败原因。
---

## 任务集（26 个，5 级难度）

每个任务由纯 Python 定义（`setup` 生成输入文件 → agent 执行 → `verify` 判定），不依赖 shell 特定语法，Win/Linux 行为一致。

| 难度 | 数量 | 示例 |
|---|---|---|
| L1 简单 | 5 | 写文件、CSV→JSON、统计行数、查找替换、建目录树 |
| L2 一般 | 5 | 最大最小值、日志解析、偶数求和、JSON 合并、修语法错误 |
| L3 中等 | 5 | 词频排序、跨文件移动函数、按前缀整理、CSV 过滤、修 2 个逻辑 bug |
| L4 进阶 | 6 | 长文档精准提取、精准改配置、嵌套目录搜索、数据聚合、定位隐藏 bug、**脑筋急转弯陷阱题** |
| L5 专家 | 5 | 500 行数据多步处理、跨模块实现、批量重命名+依赖更新、模糊需求分析、全局搜索聚合 |

能力维度覆盖：`file` `read` `edit` `bash` `grep` `debug` `context` `refactor` `code` `plan` `reasoning`。

> L4 含一道**陷阱题** `l4-riddle-driving`（脑筋急转弯：洗车店只有 10 米，走过去还是开车过去？正确答「开车过去」，理由不重要）。模型若被表面逻辑（10 米→走过去）带偏则判 FAIL——专门测 agent 是"真理解"还是"跟直觉走"。

---

## 评分标准

参考 [Artificial Analysis Coding Agent Index](https://artificialanalysis.ai/coding-agents) 方法论（pass@1 多轮平均 + token 消耗统计）：

| 指标 | 说明 |
|---|---|
| **pass@1 通过率** | 每个任务跑 N 次（默认 **5 次**），任务通过率 = 通过次数/N，整体 = 全部任务平均 |
| **难度加权分** | L1..L5 权重 `[1, 1.5, 2, 2.5, 3]`，越难权重越高 |
| **Token 效率分** | 单任务均值 ≤ 预算（默认 20000 tokens）拿满分，超出线性衰减 |
| **综合分 (0-100)** | `0.7 × 难度加权通过率 + 0.3 × Token 效率分` |

另外输出：总 Token、平均单任务 Token、Token/成功任务、平均耗时、分难度/分能力统计、单任务明细表。

---

## 快速开始

### 1. 准备

- Python 3.10+
- 一个可用的 agent 后端：
  - **imo**：把 `imo.exe` 放到仓库父目录 `output/` 下，或加入 PATH，或 `--agent-path` 指定
  - **OpenClaw**：`openclaw` 命令加入 PATH
- 模型 API Key（imo 会自动读取其 `imo-data/console/config.json`，也可用参数显式指定）

### 2. 配置模型

**imo**（三种方式任选）：

```bash
# 方式一：imo 自己的配置文件 output/imo-data/console/config.json（自动加载）
# 方式二：命令行参数
python -u harness-runner.py --agent imo --provider deepseek --model deepseek-v4-flash --api-key sk-xxxx
# 方式三：环境变量（imo 原生支持）
```

**OpenClaw**：OpenClaw 用自己的配置系统管理模型，runner 不传 key，只要 `openclaw` 命令可用且已配置好模型：

```bash
# 方式一：环境变量（优先级最高）
export DEEPSEEK_API_KEY="sk-xxxx"        # DeepSeek
export ANTHROPIC_API_KEY="sk-ant-xxxx"   # Anthropic
# 方式二：CLI 配置（写入 ~/.openclaw/openclaw.json，持久化）
openclaw config set models.providers.deepseek.apiKey "sk-xxxx"
openclaw models set deepseek/deepseek-v4-flash
# 方式三：交互式向导
openclaw onboard
# 验证
openclaw models list
openclaw models status
```

### 3. 运行

```bash
# 全量 26 任务，每任务 5 次取平均（默认行为）
python -u harness-runner.py --agent imo

# 换 OpenClaw 驱动
python -u harness-runner.py --agent openclaw

# 只跑某级 / 某几个任务
python -u harness-runner.py --agent imo --level 4
python -u harness-runner.py --agent imo --tasks l1-hello,l4-riddle-driving

# 自检：不调 agent，校验 26 个任务定义是否正常
python harness-runner.py --selftest
```

### 4. 结果

输出到 `results/<时间戳>/`：

- `summary.json` — 全部指标（机器可读）
- `report.md` — 人类可读报告（总体 / 分难度 / 分能力 / 单任务明细）
- `raw_runs.json` — 每次运行的原始数据（含 token、耗时、失败原因）

---

## 命令行参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--agent` | `imo` | agent 后端：`imo` 或 `openclaw` |
| `--agent-path` | 自动 | agent 可执行文件路径 |
| `--runs` | `5` | 每个任务跑几次（最终成绩取平均） |
| `--tasks` | 全部 | 逗号分隔的任务 id，如 `l1-hello,l2-log-parser` |
| `--level` | 全部 | 只跑某一级（1-5） |
| `--timeout` | `600` | 单次 agent 调用超时秒数 |
| `--provider/--model/--api-key` | 自动读配置 | imo 模型配置（显式指定优先） |
| `--tools` | `read,bash,edit,write,grep,find,ls` | imo 工具白名单 |
| `--keep-ws` | 关 | 保留临时 workspace（调试用） |
| `--check` | 关 | **环境自检**：探测 Python/imo/openclaw/API Key，报告缺什么、怎么补（别的 agent 第一步先跑这个） |
| `--selftest` | 关 | 只校验任务定义，不调 agent |

---

## 目录结构

```
harness-bench/
├── harness-runner.py      # 主驱动：agent 适配器 + 运行循环 + CLI
├── scoring.py             # 评分体系（pass@1 / 难度加权 / token 效率 / 综合分）
├── tasks/
│   └── harness_tasks.py   # 26 个任务定义（setup/verify 成对）
└── results/               # 测试结果输出（gitignore）
```

## 给 AI Agent 的评测提示词（可直接复制）

> 请用 HarnessBench 基准评测当前环境的 Agent Harness 能力。严格按下面步骤执行，不要跳过、不要向用户索要任何 API Key：
>
> **第 1 步 · 准备**
> 1. 克隆仓库 `https://github.com/Gejinmiao/harness-bench.git`，进入 `harness-bench` 目录；
> 2. 确认 Python 3.10+ 可用（`python --version`）。
>
> **第 2 步 · 环境自检（必做，不要跳过）**
> 3. 运行 `python -u harness-runner.py --check`，它会探测 Python / imo / openclaw / 模型 API Key 是否就绪，并给出缺失项的补救提示；
> 4. 根据输出补齐缺失项：
>    - **imo 缺失**：把 `imo.exe` 放到仓库父目录 `output/` 下，或加入 PATH，或用 `--agent-path` 指定；
>    - **openclaw 缺失**：确认 `openclaw` 命令在 PATH（只在你选择 openclaw 驱动时需要，用 imo 可忽略）；
>    - **API Key 缺失**：**不要向用户索要 key**。imo 会自动读取其配置文件 `output/imo-data/console/config.json` 里的 `provider/model/apiKey`；openclaw 用自身配置系统（环境变量如 `DEEPSEEK_API_KEY`、`~/.openclaw/openclaw.json`、或 `openclaw models set`）。去这些位置确认 key 已配置即可——运行命令时**不要传 `--api-key` 参数**，让 runner 自动读取。若确实找不到，如实告诉用户环境缺 key。
> 5. 自检全部 OK 后继续；imo 可用优先用 imo，否则用 openclaw。
>
> **第 3 步 · 冒烟验证（小步快跑，别直接上全量）**
> 6. 先只跑 1 个最简单任务验证整条链路：`python -u harness-runner.py --agent imo --tasks l1-hello --runs 1`（仅 1 次调用）；
> 7. 看到 `[PASS] l1-hello` 再继续下一步；若失败，先修环境/配置问题，不要带病跑全量（全量 130 次调用，中途失败损失很大）。
>
> **第 4 步 · 全量评测**
> 8. 运行 `python -u harness-runner.py --agent imo --runs 5`（26 任务 × 5 次 = 130 次调用，耗时较长属正常，耐心等待，不要中断）；
> 9. 若必须中断或某任务批量失败，可用 `--tasks <id列表>` 或 `--level <1-5>` 分段补跑。
>
> **第 5 步 · 汇报结果**
> 10. 读取 `results/<最新时间戳>/summary.json` 与 `report.md`，汇报：综合分、pass@1 通过率、难度加权分、Token 效率分、总 Token 消耗、分难度通过率，以及每个失败任务及失败原因。
