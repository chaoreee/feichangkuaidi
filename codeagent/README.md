# codeagent 接口约定 — 真实对战自动闭环

> 本文件是 **Claude Code（策略侧）** 与 **内网 codeagent（对战侧）** 之间的接口契约。
> codeagent 本体在内网实现（不在本 repo）；repo 侧只定义输入/输出的文件协议与 `analysis/` 消费方式。
> 新 session 实现 repo 侧改造时，严格按此契约。

---

## 0. 能力假设（已与用户确认）

| 项 | 假设 | 影响 |
|---|---|---|
| 触发方式 | **手动触发** | 每轮 A/B 需人工跑两个 batch |
| 对手可控 | **可指定对手 id** | A/B 按对手 id 配对 |
| seed 可控 | **不可控**（平台随机） | 配对含运气噪声，靠 N≥30 + 多对手分摊 |
| 每批版本数 | **一轮只跑一个 client 版本** | A/B = 两个独立 batch（baseline + variant），同对手列表 |
| 结果回流 | **落共享 reports 路径，Claude pull** | raw log 留内网，只有 `reports/`（tracked）流回 |

---

## 1. 闭环总览

```
Claude（本 repo）                codeagent（内网）                 Claude（下一 session）
─────────────                   ──────────────                    ──────────────
改代码 + 写 batch.yaml    →   pull ref，打包 client/ZIP
commit/push loop_engr         手动触发：对 opponent_pool 跑 N 局
                              收 match_*.log → logs/platform/<batch>/
                              跑 python3 -m analysis → reports/
                              落 reports/batches/<batch>.json
                        ←   push reports/ 到共享路径       pull
读 ab_report.md / 群体归因，定下一轮
```

**A/B = 两个 batch**：baseline batch（ref=origin/main）+ variant batch（ref=当前分支），**同一 opponent_pool**。

---

## 2. 输入契约：`codeagent/batch.yaml`

Claude 在分支上写此文件，commit/push。codeagent 手动拉取并据此跑一批对战。

```yaml
# codeagent/batch.yaml
batch_id: iter33-static-planner-v1     # 唯一 id；落盘路径用
variant: static-planner-v1              # 标签；A/B 时区分 baseline/variant
ref: origin/loop_engr                   # 打包此 ref 的 client/ 为平台 ZIP
opponent_pool:                          # 指定对手 id 列表（A/B 两 batch 须一致）
  - "2735"
  - "2814"
  - "2738"
  - "2614"
  - "2613"
games_per_opponent: 1                   # K 对手 × M 局 = N；须 N ≥ 30
```

**字段语义**：
- `batch_id`：全局唯一，建议 `<iter>-<variant>`。baseline batch 用 `<iter>-baseline`。
- `variant`：自由标签，但 A/B 配对时 baseline batch 须含 `baseline`。
- `ref`：git ref（分支/tag/commit）。codeagent `git fetch && git checkout <ref>` 后把 `client/` 打成 ZIP（start.sh 在 ZIP 根，不套目录）。
- `opponent_pool`：对手 id 列表。A/B 的两个 batch **必须完全一致**（顺序也一致，便于按 game_index 配对）。
- `games_per_opponent`：每个对手跑几局。seed 不可控时，建议 M≥2 降低运气噪声；K×M ≥ 30。

---

## 3. 输出契约：codeagent 落盘

codeagent 跑完后，在 repo 工作区落以下文件（raw log 内网留存，reports/ 入库回流）：

```
logs/platform/<batch_id>/
  match_<ts>_<round>_<me>_vs_<opp>_<hash>.log      # 完整 trace（gitignored，内网留存）

reports/
  <matchId>.report.json                             # 单局 Report（tracked，analysis 产）
  <matchId>.compact.log                             # 精简 trace（tracked，analysis 产）
  batches/<batch_id>.json                           # 批次元数据（tracked，codeagent 产）
```

`reports/batches/<batch_id>.json`（codeagent 生成）：
```json
{
  "batch_id": "iter33-static-planner-v1",
  "variant": "static-planner-v1",
  "ref": "origin/loop_engr",
  "commit": "042e16d",
  "clientVersion": "iter33-def",
  "opponent_pool": ["2735", "2814", "2738", "2614", "2613"],
  "games_per_opponent": 1,
  "matches": [
    {
      "matchId": "match_20260705_120000_0_2696_vs_2735_ab12cd",
      "opponent": "2735",
      "game_index": 0,
      "report": "match_20260705_120000_0_2696_vs_2735_ab12cd.report.json"
    }
  ],
  "created_at": "2026-07-05T12:30:00"
}
```

**字段约束**：
- `commit` / `clientVersion`：codeagent 从 `git rev-parse --short <ref>` 与 trace `Startup version=` 抽取，写入元数据。
- `opponent`：从 matchId 的 `_vs_<opp>_` 段或平台回执抽取。
- `game_index`：同一对手的第几局（0-based），用于多局配对。
- `report`：相对 `reports/` 的 report.json 文件名。
- `matches[]` 顺序 = opponent_pool × games_per_opponent 的展开顺序。

---

## 4. A/B 配对：`reports/batches/compare_<id>.json`

两个 batch 跑完后，Claude 写此文件，跑 `--compare` 出 A/B 报告。

```json
{
  "comparison_id": "iter33-static-planner",
  "baseline_batch": "iter33-baseline",
  "variant_batch": "iter33-static-planner-v1"
}
```

**aggregator 配对规则**（repo 侧实现）：
1. 读两个 batch.json，**校验 `opponent_pool` 完全一致**（顺序一致）；不一致则报错拒绝配对。
2. 按 `(opponent, game_index)` 配对：baseline 的 `(2735,0)` ↔ variant 的 `(2735,0)`，依此类推。
3. `games_per_opponent > 1` 时，先按 opponent 聚合（均值/胜率），再按 opponent 配对。
4. 输出 `reports/ab_report_<comparison_id>.md`：配对胜率、均分差、分项差、95% CI；**标注"seed 不可控、配对含运气噪声、N=K×M"**。
5. 同时跑**群体归因段**（按对手类分桶，见 §5），不只 A/B 均值。

---

## 5. 群体归因（analysis 侧，并行于 A/B）

每个 batch 独立产 `analysis_report.md`，头部加**按对手分桶**的群体统计（取代单局时间线导向）：
- 对手分类：用 P1-A 已抽的对手逐帧轨迹/用冰/设卡，聚类为 `speed-route` / `quality-route` / `guard-type`（首版可按对手终局鲜度+用冰数简单分桶，后续迭代细化）。
- 每桶：胜率、我方/对手分项均值、分项差。
- 一眼看出"对哪类对手差在哪个分项"，驱动下一轮选型。

单局时间线（`timelines.md`）降为异常下钻入口，不作为迭代主线。

---

## 6. 一次 A/B 迭代完整流转

1. **Claude**：在分支上改代码 + 写 `codeagent/batch.yaml`（variant ref + opponent_pool），commit/push。
2. **人工触发 codeagent（baseline）**：用 `ref: origin/main` + `variant: baseline` + **同一 opponent_pool** 跑一批 → 落 `reports/batches/<iter>-baseline.json` + reports/，push 共享路径。
3. **人工触发 codeagent（variant）**：用 `ref: <当前分支>` + `variant: <label>` + **同一 opponent_pool** 跑一批 → 落 `reports/batches/<iter>-<variant>.json` + reports/。
4. **Claude**：pull，写 `reports/batches/compare_<id>.json`，跑 `python3 -m analysis --compare reports/batches/compare_<id>.json`。
5. **Claude**：读 `ab_report_<id>.md` + 群体归因段，定下一轮（合入 / 回退 / 调参）。

> 注：baseline batch 可跨迭代复用（同一 main commit），不必每轮重跑——除非 main 前进。compare.json 指向哪两个 batch 就配哪两个。

---

## 7. repo 侧待实现（新 session 的活）

| # | 文件 | 内容 |
|---|---|---|
| 1 | `codeagent/batch.yaml` | 示例文件（本目录已规划，见 §2） |
| 2 | `analysis/__main__.py` | 加 `--compare <file>` 入口；`--batch <dir>` 单 batch 解析入口 |
| 3 | `analysis/aggregator.py` | 新增按 opponent 配对（保留 sim seed 配对）；`opponent_pool` 一致性校验；多局聚合 |
| 4 | `analysis/aggregator.py` | 群体归因段：对手分桶 + 每桶胜率/分项差（§5） |
| 5 | 测试 | `test_aggregator_compare.py`：两 batch 配对、opponent_pool 不一致报错、多局聚合、与 sim seed 配对共存 |

**铁律**：sim seed 配对路径（`ab_pair` aggregator.py:394）**保留不动**，sim 仍按 seed 配对；新路径只对 `--compare` 的平台 batch 生效。

---

## 8. transport 说明

"共享 reports 路径 + Claude pull" 的具体传输（git push 到 results 分支 / 共享 FS 同步 / rsync）由内网 codeagent 环境决定，**本契约只规定文件布局与 schema**，transport 无关。约定：codeagent 把 `reports/`（tracked）写进 repo 工作区并推送，`logs/platform/`（gitignored）留内网。
