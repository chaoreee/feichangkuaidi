# Iter 36 计划 — 资源感知路线重评（方案 B）：大路双冰鉴路线杠杆

> 触发：Iter 35 路线绕行归因完成后，复核 `samples/map_config.json` 的 `visibleResources` 发现完整资源拓扑对真实图有效——揭示 me 的山路绕行漏领 S03/S07 双冰鉴 + S09 快马，而对手 `on=` 重建路线正是走这条大路。`rules.py` 严格投影（移动损耗口径 + 冰鉴 +10×N）证实大路路线端鲜度 ~100、鲜度分 ~180，vs me 现状 150 → **+20 鲜度分真杠杆**，me 没选、对手选了。
> 约束：用户要求先把现有 reports 充分利用后再上平台。Iter 33/34 已合入但未在真实平台验证；Iter 36 stage 后**一轮真实 A/B 同时验证三轮**（33+34+36）。

## 0. 背景：Iter 35 结论的边界

Iter 35 证伪「路线是鲜度杠杆」**仅在「山路 vs 水路」窄对比下成立**：
- 山路（me 现状 `S01→S06→S08→S10→S13→S14→S15`，1 冰鉴@S06 + 短马@S08）vs 水路（Dijkstra 帧最优，0 冰鉴）：山路 +147（冰鉴+任务+马抵消多损的 4.9 鲜度）。✅ 仍成立。
- **但存在第三选项 me 没评估**：大路 `S01→S02→S03→S07→S09→S10→S13→S14→S15`，经 S03/S07 双冰鉴 + S09 快马。Iter 35 未评估因 compact.log 不记资源表、且只对比了 Dijkstra 帧最优路。

## 1. 资源拓扑（关键新信息）

`samples/map_config.json` 的 `visibleResources`（**对真实图有效**：同 15 节点 S01-S15；真实图仅多 2 条捷径边 S10-S13/S11-S14，资源按节点分布不受影响；已逐边核对）：

| 节点 | 资源 | me 现状（山路） | 大路 |
|---|---|---|---|
| S03 | ICE_BOX, PASS_TOKEN, INTEL | 不经 | ✅ 领冰鉴 |
| S04 | SHORT_HORSE, BOAT_RIGHT, INTEL | 不经 | 不经 |
| S06 | ICE_BOX, INTEL | ✅ 领冰鉴 | 不经 |
| S07 | ICE_BOX, SHORT_HORSE | 不经 | ✅ 领冰鉴+短马 |
| S08 | SHORT_HORSE, PASS_TOKEN, INTEL | ✅ 领短马 | 不经 |
| S09 | FAST_HORSE, OFFICIAL_PERMIT | 不经 | ✅ 领快马 |
| S10/S11/S13 | INTEL/PASS_TOKEN/OFFICIAL_PERMIT | 经 | 经 |

→ me 山路领 1 冰鉴+1 短马；大路领 **2 冰鉴 + 快马 + 短马**。处理站（需 processRound 停靠）：S02/S04/S05/S11/S13——S03/S07/S09 **非处理站**，大路经它们不额外停靠（仅 CLAIM_RESOURCE 自身处理帧）。

## 2. 路线 ROI（`rules.py` 严格投影，移动损耗口径 + 冰鉴 +10×N）

| 路线 | 帧 | 移动损耗 | 冰鉴 | 端鲜度(移动) | 鲜度分 |
|---|---|---|---|---|---|
| 山路（me 现状） | 329 | 21.875 | 1 | 88.12 | 158 |
| 水路（Dijkstra 最优） | 322 | 16.98 | 0 | 83.02 | 149 |
| **大路（S03+S07 双冰鉴 + S09 快马）** | 353 | 19.835 | 2 | 100.17→100 | **180** |

- me 实际端鲜度 83.36（移动 88.12 − 处理/天气停靠 ~4.8）。
- 大路移动端鲜度 100，扣同样停靠 ≈ **95**，鲜度分 ~171 → 比 me 现状 150 多 **+20**，追平对手 173。
- 对手 `on=` 重建路线 = `S01→S02→S03→S07→S09→S10→S11→S14→S15`（大路变体）——**对手正是走大路拿双冰鉴+快马得 96.21**。交叉验证成立。
- 大路多 24 帧（353 vs 329）→ 时间分约 −3；多领 2-3 资源的处理帧约 −2。**净估 +17**（鲜度 +20 − 时间 3 − 处理 2，未计好果改善：双冰鉴+高鲜度少转坏 1-2 篓 = +2-4 分）。须 §1 精算确认。

## 3. 执行计划

### §1 归因（现有 reports + samples，不重跑）
1. 扩展 `analysis/route_audit.py`（或新模块 `route_planner_eval.py`）：读 `samples/map_config.json` 的 visibleResources + 真实图拓扑（从 compact.log Map 行），枚举候选路线（山路/水路/大路/S07 混合/S09 混合），用 `rules.py` 严格投影每条终局分：
   - 冰鉴 +10×N（端鲜度封顶 100）、马速（FAST_HORSE base 1200 / SHORT_HORSE 1150，仅持续 HORSE_DURATION 帧，按实际覆盖路段算）、处理站 processRound 停靠帧、好果转坏阈值（90/80/70…）、用时分、任务分（按路线途经任务节点）。
   - **必须含处理站成本 + 马有效持续帧 + 好果阈值**——路线方向已错两次（Iter 34 §1、Iter 34 勘误），§1 不准手算。
2. 精算大路 ROI vs 山路（me 现状）：得逐分项 Δ（送达/任务/时间/好果/鲜度/悬赏）。若群体均值 +（鲜度 +20 − 时间 −3 − 处理 −2 + 好果 +2~4 ≈ +17~21）→ 杠杆确认。
3. 在真实图拓扑 + 真实资源上跑 `strategy/static_planner.py` `plan_route`：看它是否选大路。Iter 26-28 sim A/B 中性是 samples 图无此资源布局分析；真实图上是首次验证。
4. 交叉验证对手 `on=` 路线 = 大路（已初验，§1 固化）。

**§1 产出**：`docs/iter36_route_eval.md`（路线 ROI 报告）+ 扩展模块 + 单测。**不合入策略改动。**

### §2 stage（若 §1 确认大路 +）
- 优选：开 `ENABLE_STATIC_PLANNER`（若 §1.3 证 plan_route 在真实图选大路）。
- 备选：在 `decision.py` `_plan` 加资源感知路线选择（双冰鉴投影优于山路捷径时选大路，过 `_can_afford` + ΔEV 地板）。
- sim 50 种子回归门：0 STUCK / 0 对账 / 分段不回归 / mean 不降。注：sim 是 samples 图镜像自博弈，大路收益可能不重现 → sim 仅作"不破坏 baseline"门，**收益须真实 A/B**。

### §3 一轮真实 A/B（codeagent N≥30，用户重跑）
新 client（含 iter33+iter34+iter36 改动）对平台真实对手池 N≥30：
1. Iter 33 验证：交付率 96%→~100%（3 局未交付风暴修复）。
2. Iter 34 验证：好果 97→98（冰鉴阈值 78→81）。
3. Iter 36 验证：me 是否改走大路？鲜度 82.6→90+？quality-route 桶 W 0.43→?
4. 正向合入；负则删（§0.5 纪律）。

## 4. 纪律与风险

- **路线方向已错两次**（Iter 34 §1 误判最优路、Iter 34 勘误误读 `on=`）。§1 必须用 `rules.py` 严格算全分项，禁手算；§3 真实 A/B N≥30 正向才合入。
- 资源拓扑来源是 `samples/map_config.json`，非真实 start 消息。已逐边核对真实图是 samples 图 +2 边，资源按节点分布不变；但决赛若换图，资源布局可能变——策略须**通用**（读 start 的资源表动态决策，不硬编码大路路线）。
- 大路多 24 帧 + 处理帧：若时间预算紧张（对手设卡/天气恶化），大路可能无法按时交付。stage 须过 `_can_afford` 时间守卫，时间不够回落山路。

## 5. 新 session 入口

从 §1.1 开始：扩展 `analysis/route_audit.py` 读 `samples/map_config.json` visibleResources + 真实图拓扑，枚举候选路线 + `rules.py` 投影。先读 `docs/iter35_route_audit.md`（Iter 35 结论边界）+ 本文件 §1 资源拓扑 + `reports/route_audit.json`（me 现状路线）。
