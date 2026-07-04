# logs/ — 对局语料采集目录（client 之外）

这里存放**从赛题平台/仿真器取回的对局 trace 日志**（`match_*.log`），供仓库侧 `analysis/` 模块
（**位于 client 之外**）事后解析、跨局聚合，再由 Claude Code 读聚合报告做归因。本目录不属于交付件
（`client/`），只用于本地/仓库侧的分析闭环。

> Iteration 21 起迭代方式为**分析器驱动证据型**（见 `docs/iteration_plan_v2.md`）：
> client 只记 trace 日志、不含分析模块；`analysis/` 解析多份 trace → 结构化 `Report` → 跨局聚合报告。
> 代码抽取事实、AI 只做解释。Claude Code 不直读 10w 字原始 trace，只读聚合报告 + 被标记单局 Report。

## 目录结构

```
logs/
├── real/            # 真实平台对局：从交付件 client/logs/ 取回的 match_*.log
│   └── ...          #   source=platform（路径推断）
├── sim/             # 仿真器（Phase A）对局
│   ├── baseline/    #   variant=baseline（父目录名推断）
│   └── tuned/       #   variant=tuned（A/B 配对用）
└── README.md
```

`logs/real/` 与 `logs/sim/` 都是**累积语料库**：`python3 -m analysis` 每次读取其下全部 `match_*.log`
重新解析聚合，新取回的对局只往里追加。source/variant 由路径自动推断（可被 `--source`/`--variant` 覆盖）。

## 日志从哪来

运行期 `client/` **只记录人类可读 trace 日志**（`client/logs/match_<matchId>_<playerId>.log`，逐行 flush）。
对战平台运行时无需实时分析，故 client 不写结构化报告、不含分析代码。

- 本地对 `scripts/mock_server.py` 跑：日志直接生成在 `client/logs/`（已 gitignore，不入库）。
- 提交到平台：交付件在平台运行时同样写 `client/logs/`；对战结束后连同交付件一起**下载回本地**，
  再把 `match_*.log` 复制到 `logs/real/`。
- 仿真器（Phase A）把日志直接落 `logs/sim/<variant>/`。

trace 事件类型：`Startup / Register / Start / Ready / Frame / Action / Projection / ModeChange / Eta /
GuardDecision / Rejected / CanAffordBlock / Recv / Error / Over / Score / Shutdown`。
其中 `Rejected`/`CanAffordBlock` 是 decision 内部信号（被拒动作 / canAfford 拦截）写成 trace 行，供分析器还原。

## 采集流程

1. 拿到一场对局的 `client/logs/match_*.log`。
2. 复制到 `logs/real/`（平台）或 `logs/sim/<variant>/`（仿真）。
3. 跑 `python3 -m analysis logs/real logs/sim --out-dir docs` →
   `docs/analysis_report.md`（+ 存在 variant 时的 `docs/ab_report.md`）。
4. Claude Code 读聚合报告（+ 被标记的 3-5 份单局 Report）做归因，**不直读原始 trace**；
   仅当某单局报告指向某帧段可疑时，按帧段取一小段 `.log` 深挖。
5. 同步更新 `CLAUDE.md`（能力矩阵 + 迭代日志）与 `CHANGELOG.md`。

## 分工边界（铁律）

- **client = 只记 trace 日志**（交付件，不含分析、不写结构化报告）。
- **analysis/ = 仓库侧纯确定性 Python**（client 之外）：`parser` 从 trace 抽取事实（100% 准确、可复现、可单测）、
  `aggregator` 跨局聚合。**不做优化、不出建议**。
- **AI = 只读报告做解释**：基于结构化事实回答"为什么输/该怎么改"。
- 单局只作**假设来源**；决策须基于全语料聚合统计 + 置信区间 + 分段表现（防单点过拟合，§3.7）。
