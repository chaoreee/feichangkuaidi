# 校准日志 v1 — Phase B 静态规划器仿真 A/B

> 对应 `docs/p0_attribution_batch2.md` §6、`docs/iteration_plan_v2.md` §1.2 "done"标准。
> 本文件记录 Phase B `static_planner` 作 variant 的仿真 A/B 结果与处置决策。
> **结论：v1 未通过 A/B 门槛，`ENABLE_STATIC_PLANNER` 保持默认关，不合入。**

---

## 1. 实验设置

- 仿真器：`scripts/sim_server`（Phase A 高保真自博弈，物理复用 `core/rules.py`），50 种子 × 2 侧 = 100 player-games/批。
- baseline：`--variant baseline`（`ENABLE_STATIC_PLANNER=False`）。
- variant：`--variant tuned --static-planner`（`ENABLE_STATIC_PLANNER=True`）。
- 指标：mean 终局分、交付率、交付帧、卡死、对账误差。

## 2. 结果

| 指标 | baseline | variant(任务优先+cap25) | variant(冰鉴优先,无cap) |
|---|---|---|---|
| mean 终局分 | 747.8 | **747.8（中性）** | 748.3（+0.5） |
| 交付率 | 1.000 | 1.000 | 1.000 |
| 交付帧 mean | 455.4 | 455.4 | 480.3（+25） |
| 卡死 | 0 | 0 | 0 |
| 对账误差 | 0 | 0 | 0 |
| 分数范围 | 731–762 | 731–762 | 727–770 |

- **任务优先 + cap25**（committed）：冰鉴绕路被任务绕路抢占 → variant 不触发任何动作，与 baseline 逐帧一致（中性，零回归）。
- **冰鉴优先 + 无 cap**（对照）：冰鉴绕路触发，交付鲜度 82.66→92.56（+18 分）、好果 98→100（+4），但 **task_base 140→120（−10 分）**、交付 +21 帧（−2 分）→ 单局净 +10（seed1：760→770），但跨 50 种子 mean 仅 +0.5（部分种子冰鉴绕路挤占任务致负）。

## 3. 归因：为何 +24 上界未兑现

`p0_attribution_batch2.md` §4.5 投影"质量路线 +24"是**上界**——假设 task_base 不变（150）、鲜度 80→93。仿真暴露被该假设掩盖的两个成本：

1. **冰源稀缺**：本图直送路线仅过 1 个冰源（S06），单篓冰鉴（+10）不足以改变交付鲜度（总损耗 ~23）。要多篓冰鉴须绕路 S03/S07 → 绕路帧挤占交付/任务预算。
2. **任务-冰鉴时间预算零和**：冰鉴绕路 ~21 帧 ≈ 1 个任务（score 20）的时间。冰鉴优先 → 丢 1 任务（task_score 180→170，−10）；任务优先 → 冰鉴绕路无机会触发（中性）。**分项式（piecemeal）绕路无法同时最大化 task 与 ice**——二者争同一 spare-time 预算。

真实对手在 trace 中达成 fresh 93 **且** task 165（多任务），说明实战存在"冰源与任务点共址"的高效路线，而我方分项式 `_plan` 瀑布（task 绕路 / ice 绕路 / 路线选择各自为政）找不到它。这正是 `iteration_plan_v2.md` §6 设想的全量 `static_planner`（联合优化 task bundle + ice + route）要解决的问题——v1 只落地了分项子能力，未做联合求解。

## 4. 处置

| 项 | 决策 | 依据 |
|---|---|---|
| `ENABLE_STATIC_PLANNER` | **保持默认关** | mean +0.5（< 仿真噪声）且有 task 回归风险，未过 §1.2 "mean 分正向且无分段回归"门槛 |
| 代码 | **保留作 variant** | `static_planner.py`（freshness_optimal_path / project_route / plan_route）+ `_ice_detour_target` 经 258 单测验证、异常安全，是全量联合规划器的平台 |
| `CLIENT_VERSION` | 不 bump（未合入运行期行为） | flag 默认关 → baseline 行为零变化 |

## 5. 已落地能力（保留，flag 关）

- `strategy/static_planner.py`：`freshness_optimal_path`（鲜度加权 Dijkstra）、`project_route`（rules.py 终局分投影 + 冰鉴模型：+10 鲜度/次、−1 帧、抵 1 转坏跨越）、`plan_route`（候选路线 × 冰鉴用量取投影分最高，改道门控 MIN_ROUTE_GAIN）。
- `decision.py`：`_select_path`（flag-on 用 plan_route，否则时间最优）、`_freshness_rescue`（阈值 91 护 90 阈值带）、`_maybe_claim`（ice_keep=3）、`_ice_detour_target`（就近冰源绕路，过 _can_afford + ΔEV 门）。
- `sim_server.py`：`--static-planner` CLI flag 翻转 config（供后续 A/B）。
- 16 项新单测（`tests/test_static_planner.py`），总 258 过。

## 6. 下一步（替换 batch2 §6 的 Iter 26）

1. ~~**全量联合 static_planner**~~ → **Iter 27 已落地（见 §7），A/B 仍未过门槛**。
2. **仿真器保真度**：sim task_base 恒 140；冰源拓扑 sim 已用真实 `samples` 图（初赛图），但决赛换新图——策略须通用（读 `start` 动态决策），不能针对 samples 适配。
3. **N≥30 真实 trace**：累计已 30，继续收割使分项结论脱离"假设级"。
4. 全量 planner 过 sim A/B（mean 正向 + `mid_lead`/`delivered` 段不回归）+ 真实 trace 二次校准后才合入默认。

---

## 7. Iter 27 联合规划器（task + ice + route 一体求解）

针对 §3 根因（v1 分项式 task-ice 零和）与 §5 评审（`project_route` 冻结 task_base、`plan_route` 候选集过窄、`_ice_detour_target` 架构错），落地真正的联合求解：

- `project_route` 加 `_path_pickups`：沿途自动建模 task 领取（贪心到 130 封顶）+ ice 收集（+停靠帧及其鲜度损耗）——路线选择首次能权衡"绕冰源 vs 绕任务点"的零和。
- `plan_route` 候选集扩展：时间最优 + 鲜度最优 + 经冰源/任务点 waypoint 的拼接路线（含 ice+task 二段组合，覆盖共址路线）；每候选过 `project_route`×ice用量 取终局分最高，ΔEV 门控改道。读 `start` 拓扑动态生成，不写死节点（**通用**）。
- 删除 `_ice_detour_target`（分项式元凶）+ orphan 参数；flag-on 时 `_plan` 跳过 `_task_detour_target`（避免与 plan_route 双重决策）。91/3 保留——移除分项绕路后，它们经路线耦合兑现冰鉴收集/使用。

**Bug 修复**：初版 waypoint 拼接路径可含回溯段（如 S03→S06 绕回 S01），逐帧重规划时在回环处振荡卡死（7/50 局 STUCK）。修法：`_via_path` 拒绝非简单路径（含重复节点者）。修复后 0 STUCK。

**A/B（50 种子）**：

| 指标 | baseline | tuned(联合规划器) |
|---|---|---|
| mean 终局分 | 747.8 | **744.1（−3.7）** |
| 交付帧 mean | 455.4 | 515.0（+60） |
| 交付率 | 1.000 | 1.000 |
| STUCK | 0 | 0 |

**多图单测（通用性证据）**：同一规划器、同一输入在两张图上做出相反决策——冰源顺路图（S03 绕路短）→ 改道；冰源偏远图（S03 绕路长）→ 保直送。决策完全由读 `start` 拓扑的 ΔEV 投影驱动，不依赖具体图。

**根因（仍未过门槛）**：flag-on 选了 +60 帧的鲜度绕路（投影 +7，实测 −3.7）。投影**系统性低估长绕路时间成本**：`path_frames` 用默认天气系数，未建模暴雨/山雾对水路/山路的移动减速；长绕路水路段多、被低估更甚 → 投影高估长路线收益。而**未来天气对客户端隐藏**（协议），投影无法准确预测 → 此乐观**不可彻底消除**。

**处置**：`ENABLE_STATIC_PLANNER` **保持默认关**（A/B 负，未过 §1.2 门槛；CLIENT_VERSION 不 bump）。代码保留作通用 variant 平台——机制正确（多图自适应已证）、异常安全、0 STUCK。**不强行调参逼 samples 正向**：那会过拟合初赛图（违反通用原则）；samples 结构上不提供廉价鲜度（与 v1 同结论，现已由正确联合推理得出）。

**下一步候选**：① ΔEV 门加"每帧效率"维度（gain/extra_frames ≥ 阈值）吸收不可消除的投影不确定性——拒 +7/+60=0.12/帧 的低效长绕路，纳 +7/+10 的高效短绕路；② 接受 samples 中性、靠决赛新图（冰源顺路时）自然正向。二者不冲突，可先①再上平台验。

---

> 本日志为 Phase B 的 A/B 验收记录。v1（分项式）与 v2（联合）均未过门槛，flag 保持关；根因从"分项零和"推进到"投影天气乐观（隐藏信息）"。
