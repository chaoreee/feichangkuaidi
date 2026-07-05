# analysis/ — 对局日志分析模块（非交付件，纯 stdlib）

把 `client/` 取回的 trace 日志解析成结构化指标 + 归因结论 + Markdown 报告，驱动 `client/` 迭代。
**不进交付件 ZIP**（打包只压 `client/`）。纯标准库，无第三方依赖，任意环境可跑。

## 为什么需要它

真实平台对局交付普遍在 400+ 帧，远晚于 mock（~81 帧）。600 帧的 trace 日志靠肉眼读不动，
归因（卡死/绕路/鲜度崩/进攻反噬/RUSH 过晚）需要结构化指标。Iter 9 "Claude 直接读 trace" 在
mock 下够用，真实复杂对局下不够，故建本模块。

## 用法

```bash
# 单场
py -m analysis logs/match_xxx.log
# 多场 + 跨场聚合
py -m analysis logs/match_a.log logs/match_b.log --corpus
# 指定输出目录
py -m analysis logs/match_xxx.log --out reports
```

输出 `reports/<YYYYMMDD>_<matchId>.md`（每场一份）+ 可选 `reports/<YYYYMMDD>_corpus.md`（聚合）。

## 数据流

```
trace .log ──parser──▶ MatchTrace ──metrics──▶ MatchMetrics ──diagnose──▶ [Finding] ──report──▶ Markdown
                                    │
                                    └──corpus──▶ 跨场聚合报告
```

## 模块

| 文件 | 职责 |
|---|---|
| `parser.py` | trace 文本 → `MatchTrace`（按 Startup 切分会话；对缺失字段降级兼容） |
| `metrics.py` | 单场指标：交付/鲜度归因/卡死段/阻塞 encounters/预算漂移/窗口/进攻设卡ROI/RUSH时点/直方图 |
| `diagnose.py` | 模式检测 → `Finding`（NO_DELIVER/STALL/FRESHNESS_CRASH/SPOILAGE/BUDGET_DRIFT/EST_OVER_BUDGET/OFFENSIVE_BACKFIRE/RUSH_LATE/REJECT_LOOP/WINDOW_LOSS） |
| `report.py` | 渲染 Markdown 报告 |
| `corpus.py` | 跨场聚合（复发模式、胜负分组、卡死节点复发） |
| `cli.py` / `__main__.py` | CLI 入口 |
| `tests/` | 单测（解析器/指标，含真实 mock 日志夹具） |

## 指标对照真实败局模式

- **STALL** — `state∈{MOVING,WAITING}` + 动作 NONE + 未前进的连续段（Iteration 8 复发）
- **FRESHNESS_CRASH** — 好果转坏阈值跨越 / 交付鲜度偏低，附鲜度归因（转坏 vs 动作消耗 vs 报废）
- **BUDGET_DRIFT / EST_OVER_BUDGET** — `_deliver_estimate` 估值 vs 实际交付，系统性偏差
- **OFFENSIVE_BACKFIRE** — SET_GUARD 后对手未经过（纯成本无收益）
- **RUSH_LATE** — RUSH 触发晚 / 验核到交付间隔长
- **REJECT_LOOP** — 同码拒绝 ≥3
- **WINDOW_LOSS** — 窗口告负且净耗资源

## 局限

- mock 蓝方为静态 dummy（缺 freshness/goodFruit/taskScore），mock 日志中对手/窗口/天气/拒绝相关指标为空或降级；真实平台日志才完整。
- 进攻设卡 ROI 的"对手拿悬赏"未检测（未记录 bounty 事件），仅判对手是否经过设卡节点。
- 绕路做任务亏损（DETOUR_LOSS）未实现精确检测（需路线重建，留待后续）。

## 测试

```bash
py -m unittest discover -s analysis/tests
```
