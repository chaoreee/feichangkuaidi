# Iter 36 §1 路线 ROI 重评报告 — 资源感知路线重评（方案 B）

> 触发：Iter 35 证伪「路线是鲜度杠杆」仅在「山路 vs 水路」窄对比下成立；复核
> `samples/map_config.json` 的 `gameplay.resources`（V4.2-MEDIUM schema）揭示第三选项
> **大路** `S01→S02→S03→S07→S09→S10→S13→S14→S15`（经 S03/S07 双冰鉴 + S09 快马）me 未评估。
> 本报告用 `core/rules.py` 严格投影（含**马感知逐帧 walker**——static_planner 缺的关键件），
> 硬核核算大路 ROI vs 山路（me 现状）。**§1 纯观测，不合入策略改动。**
>
> 路线方向已错两次（Iter 34 §1、Iter 34 勘误），本次禁手算，全程 `rules.py`。

## 0. 工具与新方法

新模块 `analysis/route_planner_eval.py`（+10 单测）：逐帧 walker，不复用 `static_planner.project_route`
（其 `path_frames` 恒 `base_move=1000`，**无马建模**——而 Iter 35 §5.3 已指马的密度是鲜度 gap 真因）。

逐帧模拟（纯 `core/rules.py`）：
- **移动帧**：`per_frame_move_amount(base_move)`，base_move 由当前 buff 决定（FAST 1200 / SHORT 1150 / NONE 1000）；
  每帧 `fresh −= FRESHNESS_LOSS_MOVE[rt]`；到站 `move_accum` 清零（对齐 sim，余量浪费）。
- **停靠帧**（处理 processRound / 验核 / 领取 2 / 使用 1）：每帧 `fresh −= FRESHNESS_LOSS_BASE`；**buff 同步 tick**（马在停靠期间也倒计时，对齐 sim `_tick_buffs` 每帧 tick）。
- **马策略**（对齐 client `_maybe_claim`/`_maybe_horse`）：无库存才领（FAST 优先）、无 buff 才用；
  buff 活跃期到新马节点领而不使（`HORSE_BUFF_CONFLICT`），下个节点使。
- **冰鉴**：每冰源节点领 1 篓（2 帧）；使用 post-hoc 最优（末尾、`+10×N` 封顶 100、抵 crossing）——
  对齐 `static_planner.project_route` 的 ice 模型。
- **处理站/验核**：途经 process_nodes 按 client `_plan` 行为停靠 processRound；gate 停 6 帧验核。
- 天气 coef=1.0（上界乐观，五路线同口径 → Δ 公平）；task_base=150 假设封顶（五路线均途经 ≥4 任务候选节点）。

## 1. 候选路线投影（rules.py 严格，马感知）

| 路线 | 交付帧 | (move/stop) | 移动损耗 | 冰鉴 | 端鲜度 | 好果 | 总分 | Δscore |
|---|---|---|---|---|---|---|---|---|
| 山路（me 现状） | 344 | (327/16) | 22.55 | 1 | 87.5 | 99 | 784 | — |
| 水路（Dijkstra 帧最优） | 350 | (316/34) | 18.37 | 0 | 81.6 | 99 | 773 | −11 |
| **大路（双冰鉴+快马）** | 374 | (347/25) | 20.75 | 2 | **99.2** | **100** | **804** | **+20** |
| S07 混合（双冰鉴+双短马） | 403 | (376/25) | 24.14 | 2 | 95.9 | 100 | 794 | +10 |
| S09 混合（山路+快马） | 427 | (407/19) | 27.38 | 1 | 82.6 | 99 | 766 | −18 |
| frame_optimal | 344 | (327/16) | 22.55 | 1 | 87.5 | 99 | 784 | 0 |
| fresh_optimal | 350 | (316/34) | 18.37 | 0 | 81.6 | 99 | 773 | −11 |

- `frame_optimal` = 山路（Dijkstra 帧最优，对齐 Iter 35 §1.3 三准则重合）。
- `fresh_optimal` = 水路（鲜度损耗最低 18.37，但 0 冰鉴、4 个处理站停靠 34 帧 → 总分反低）。

## 2. 大路 vs 山路 Δ（me 现状）

| 分项 | 山路 | 大路 | Δ | 机制 |
|---|---|---|---|---|
| 鲜度分 | 157 | 178 | **+21** | 双冰鉴 +10×2 封顶 100（端鲜度 87.5→99.2） |
| 好果分 | 178 | 180 | +2 | 高鲜度少转坏 1 篓（99→100） |
| 用时分 | 29 | 26 | −3 | 多 30 帧（move +20 / stop +9） |
| 送达/任务 | 240/180 | 240/180 | 0 | task_base=150 封顶共享 |
| **总分** | **784** | **804** | **+20** | — |

**杠杆确认：大路净 +20**。但机制是**第 2 冰鉴**（+10 鲜度 → +18 鲜度分 + 1 好果），**非马/路线类型**：
- 马收益小：FAST 仅覆盖 S09→S10 段 ~20 帧（HORSE_DURATION=20，恰耗尽于该段移动，未浪费在后续 S13 处理/S14 验核停靠），省 ~4 帧 ≈ +0.22 鲜度。
- 路线类型收益：大路多 ROAD（0.055/帧）vs 山路 MOUNTAIN（0.07/帧），但大路多 20 move 帧，净鲜度差仅 +1.8。
- 第 2 冰鉴（S03 或 S07）：+10 鲜度 → 主导整个 +20。

### 关键前提：+20 依赖「领 2 冰鉴」

baseline client `CLAIM_ICE_BOX_KEEP=1`（库存 <1 才领）：大路上鲜度到 S07 仍 ~91（>81 用冰阈值）
→ 不用冰 → 库存不空 → **不领 S07 冰鉴**，仅得 1 冰鉴，Δ 退化为 ~+8。

**+20 的实现路径 = 开 `ENABLE_STATIC_PLANNER`**（`STATIC_PLANNER_ICE_KEEP=3`，预囤 2 冰鉴）。
单独走大路（不开 static_planner）不兑现第 2 冰鉴。这与 §3 一致。

## 3. §1.3 static_planner 在真实图的选择

`plan_route`（flag-on）在真实拓扑 + 真实资源上跑：

- **所选路径：`S01→S02→S03→S07→S09→S10→S13→S14→S15` = 大路** ✓
- 即使 static_planner 不建模马速（`path_frames` 恒 base_move=1000，大路快马收益不可见），
  仅凭「2 冰鉴 + ROAD 低损耗」投影分最高 → 选大路。
- 即 static_planner 的 `_path_pickups` 沿途收集 2 冰鉴、`_best_score_for_path` 遍历 ice 用量
  选 k=2 → 与 §2 的 +20 机制完全一致。

**〔Iter 38 勘误〕此为静态图离线投影结论，已被 §3 真实 A/B 证伪**：实战 0/40 局走 canonical 大路
（iter31 亦 0/67），两版都走 `S01→S06→S08→S10` 山路骨架；`STATIC_PLANNER_ICE_KEEP=3` 未生效（仍领 ~1 冰鉴）；
S10 到达帧 267/268 相同、交付帧 409/406 相同 → 实战有资源/任务 waypoint 时 plan_route 不选大路
（被 ΔEV/效率门否决或候选挤出），+20 双冰鉴机制从未激活，**flag 已在 Iter 38 回退为关**。
详见 `reports/iter36_ab_out/section3_verdict.md` §3。

## 4. §1.4 对手 on= 路线交叉验证

67 局 compact.log 对手 `on=` 节点序列，按资源节点签名分类（on= 稀疏 ≤24 帧，逐帧不可确证；
但途经的关键资源节点是路线定义性特征）：

| 类 | N | 占比 | 说明 |
|---|---|---|---|
| 大路（S03∧S07） | 34 | 51% | 含 S09 快马 33 局 |
| 水路（S04∧S05） | 14 | 21% | |
| 山路（S06∧S08） | 2 | 3% | |
| other | 17 | 25% | |

- **51% 对手走大路**（S03∧S07 双冰鉴签名），低置信（on= 稀疏）但方向支持「大路是 quality-route
  鲜度 93 的来源」假设。代表性对手路线 `S01→S02→S03→S07→S09→S10→S11→S14→S15`（大路变体，走 S11-S14 捷径边 E23）。
- 仅 3% 对手走山路（me 现状路线）——me 的路线选择是少数派。

## 5. 假设与限制

- **+20 的前提是领 2 冰鉴**（开 static_planner）；baseline client 仅得 1 冰鉴 → +8。
- 马收益小（FAST 仅 S09→S10 段 20 帧、省 ~4 帧）：大路鲜度增益主因是第 2 冰鉴，非马/路线类型。
- 冰鉴 post-hoc 最优：大路 fresh_no_ice≈79 跨 90/80 两阈，2 冰鉴恰抵 2 crossing → good=100；
  与 client `fresh<81 用冰` 实际行为一致（非过乐观）。
- 处理站停靠按 client `_plan` 行为；障碍 CLEAR 帧、任务领取帧未微分（大路障碍候选点仅 S10，
  山路 S06/S08/S10，大路占优未计 → +20 对大路保守）。
- task_base=150 封顶假设；五路线均途经 ≥4 任务候选节点。
- 天气 coef=1.0；**非单调鲜度（天气峰值致额外好果转坏）未建模**——大路高鲜度下天气伤害更小，
  故好果 Δ 实际可能更大（+20 对好果保守）。绝对值上界乐观，Δ 方向稳健。
- 资源拓扑来源 `samples/map_config.json`（真实图=samples+2 捷径边 E23/E24，资源按节点不变）；
  淘汰赛/决赛换图（`map_config_variant_a.json` 已是不同资源/处理点布局），策略须通用读 `start`。

## 6. 结论与对 §2/§3 的判决

### 三项硬结论

1. **大路是净 +20 杠杆**（rules.py 严格、马感知）：双冰鉴 +10×2 封顶 100 → +21 鲜度分 + 2 好果分 − 3 用时分。
   主因是**第 2 冰鉴**，非马/路线类型（Iter 35「马的密度」假设在此图上贡献小：FAST 仅 20 帧覆盖）。
2. **static_planner 在真实图选大路**（§1.3）：开 `ENABLE_STATIC_PLANNER` 既改路线又改冰鉴领取（→2 冰鉴），
   协同兑现 +20。这是 §2 的落地路径，方向与 Iter 35 §5.2 方案 B 一致。
3. **51% 对手走大路**（§1.4，低置信）：方向支持大路是 quality-route 鲜度 93 的来源；me 山路是少数派。

### 对 §2/§3 的判决

| 阶段 | 判决 | 理由 |
|---|---|---|
| §2 stage | 🔴 **Iter 38 已回退为关** | §1.3"plan_route 选大路"是静态图结论，被 §3 真实 A/B 证伪（实战 0/40 选大路、no-op、+20 未兑现）；合入依据含 sim/静态投影影响 → flag 回退为关恢复干净基线 |
| §3 真实 A/B | 已做（N_old=67/N_new=40）| 证实 static_planner 真实对局是行为 no-op；表观回归主因对手池混杂（去偏斜后 p=0.17/0.29 不显著）。详见 `reports/iter36_ab_out/section3_verdict.md` |
| 风险 | 时间预算 | 大路多 30 帧；`_can_afford` 时间守卫兜底回落山路（实战未触发因 flag 已关） |

**〔Iter 38 勘误〕§1/§1.5 均为静态图离线投影，+20 实战未兑现**。本报告保留作机制记录（大路双冰鉴 +20 在静态图/孤岛条件下成立），不驱动策略。flag 待"修通 plan_route 实战选路根因"后由真实 A/B 正向再开。

## 7. 产出

- `analysis/route_planner_eval.py`（+10 单测）
- `reports/route_eval.json`（14KB <100KB）/ `reports/route_eval.md`
- 本报告 `docs/iter36_route_eval.md`
- 全套 414 测试过（111 analysis + 285 client + 18 sim）；sim 5 种子 sanity 零回归（1.000 交付 / 0 STUCK）
