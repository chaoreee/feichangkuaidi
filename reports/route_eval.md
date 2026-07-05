# Iter 36 §1 路线 ROI 重评（资源感知，rules.py 严格投影）

> 逐帧 walker（马感知：FAST/SHORT 按 HORSE_DURATION 帧持续、每帧 tick 含停靠）
> + 冰鉴 post-hoc 最优 + 处理站/验核停靠。天气 coef=1.0（上界乐观，五路线同口径）。
> task_base=150 假设封顶（五路线均途经 ≥4 任务节点，Δ_task=0）。

## 候选路线投影

  mountain       frame=344(move 327/stop  16) loss=22.55 ice=1 fresh=87.5 good=99 score=784.0 [d=240 t=180 g=178 f=157 ti=29]
  water          frame=350(move 316/stop  34) loss=18.37 ice=0 fresh=81.6 good=99 score=773.0 [d=240 t=180 g=178 f=146 ti=29]  Δscore=-11.0 Δframe=+6 Δfresh=-5.83 Δgood=+0
  mainroad       frame=374(move 347/stop  25) loss=20.75 ice=2 fresh=99.2 good=100 score=804.0 [d=240 t=180 g=180 f=178 ti=26]  Δscore=20.0 Δframe=+30 Δfresh=+11.79 Δgood=+1
  s07mix         frame=403(move 376/stop  25) loss=24.14 ice=2 fresh=95.9 good=100 score=794.0 [d=240 t=180 g=180 f=172 ti=22]  Δscore=10.0 Δframe=+59 Δfresh=+8.40 Δgood=+1
  s09mix         frame=427(move 407/stop  19) loss=27.38 ice=1 fresh=82.6 good=99 score=766.0 [d=240 t=180 g=178 f=148 ti=20]  Δscore=-18.0 Δframe=+83 Δfresh=-4.83 Δgood=+0
  frame_optimal  frame=344(move 327/stop  16) loss=22.55 ice=1 fresh=87.5 good=99 score=784.0 [d=240 t=180 g=178 f=157 ti=29]  Δscore=0.0 Δframe=+0 Δfresh=+0.00 Δgood=+0
  fresh_optimal  frame=350(move 316/stop  34) loss=18.37 ice=0 fresh=81.6 good=99 score=773.0 [d=240 t=180 g=178 f=146 ti=29]  Δscore=-11.0 Δframe=+6 Δfresh=-5.83 Δgood=+0

## 大路 vs 山路（me 现状）Δ

- 总分 Δ: **+20.00**
- 鲜度 Δ: +11.79（端鲜度 99.2 vs 87.5）
- 好果 Δ: +1
- 交付帧 Δ: +30（move +20 / stop +9）
- 冰鉴: 大路 2 vs 山路 1

→ 判定：**杠杆确认（大路净正）**（Δscore=+20.00）

## §1.3 static_planner 在真实图的选择

- plan_route 选: `S01→S02→S03→S07→S09→S10→S13→S14→S15`
- 是否=大路: **True**
- 投影分: 478.0
- 注: static_planner 不建模马速（path_frames 恒 base_move=1000），大路快马收益不可见

## §1.4 对手 on= 路线交叉验证

- N=67，按资源节点签名分类：{'mainroad': 34, 'mountain': 2, 'water': 14, 'other': 17}
- 大路（S03∧S07 双冰鉴）占比: 51%（含 S09 快马 33 局）
- 置信: low（on= 稀疏（仅 oppNode 变化点）；按资源节点签名分类（大路=S03∧S07 双冰鉴），非逐帧轨迹确证）
- 大路样本：
  - match_20260705_031517_015_2696_vs_2986_43603109: S01→S02→S03→S07→S09→S10→S11→S14→S15
  - match_20260705_031541_933_2905_vs_2696_03cfcc34: S01→S02→S04→S02→S04→S02→S03→S07→S09→S10→S11→S14→S15
  - match_20260705_031550_422_2696_vs_2614_c2d42d20: S01→S02→S03→S07→S09→S10→S11→S14→S15

## 假设与限制

- **+20 的前提是领 2 冰鉴**：baseline client `CLAIM_ICE_BOX_KEEP=1`，大路上鲜度到 S07 仍 ~91（>81 用冰阈值）→ 不用冰 → 库存不空 → **不领 S07 冰鉴**，仅得 1 冰鉴（+10，Δ 退化为 ~+8）。+20 的实现路径是开 `ENABLE_STATIC_PLANNER`（`STATIC_PLANNER_ICE_KEEP=3`，预囤 2 冰鉴）——而 §1.3 已证 plan_route 在真实图选大路，二者一致。单独走大路不开 static_planner 不兑现。
- 马策略对齐 client `_maybe_claim`/`_maybe_horse`（无库存才领、无 buff 才用、FAST 优先）；buff 活跃期到新马节点领而不使（HORSE_BUFF_CONFLICT），下个节点使。马收益小（FAST 仅覆盖 S09→S10 段 ~20 帧、省 ~4 帧）：大路鲜度增益主因是**第 2 冰鉴**（+10），非马/路线类型（仅 +1.8）。
- 冰鉴使用 post-hoc 最优（末尾、+10×N 封顶 100、抵 crossing）；大路 fresh_no_ice≈79 跨 90/80 两阈，2 冰鉴恰抵 2 crossing → good=100；与 client `fresh<81 用冰` 实际行为一致（非过乐观）。
- 处理站停靠按 client `_plan` 行为（途经 process_nodes 即停 processRound）；障碍 CLEAR 帧、任务领取帧未微分（documented；大路障碍候选点仅 S10，山路 S06/S08/S10，大路占优未计）。
- task_base=150 封顶假设；五路线均途经 ≥4 任务候选节点（S03/S06/S07/S08/S09/S10/S13）。
- 天气 coef=1.0；**非单调鲜度（天气峰值致额外好果转坏）未建模**——大路高鲜度下天气伤害更小，故好果 Δ 实际可能更大（+20 对好果保守）。绝对值上界乐观，Δ 方向稳健。
- 资源拓扑来源 samples/map_config.json（真实图=samples+2 捷径边 E23/E24，资源按节点不变）；淘汰赛/决赛换图，策略须通用读 start。
