# Iter 36 §1.5 真实天气审计 — 大路 +20 在真实天气下是否缩水

> 触发：§1 用 `weather_coef=1.0`（上界乐观）算出大路净 +20。但大路多 ~30 帧暴露于真实天气
> （HOT 1.5× / HEAVY_RAIN 1.3× 鲜度系数；MOUNTAIN_FOG+MOUNTAIN / HEAVY_RAIN+WATER 移动减速）。
> 本审计从 67 局 compact.log 重构逐帧天气序列，重跑马感知 walker，得出 +20 在真实天气下的分布。
> **纯观测，不合入策略改动。** §3 上平台前 的去风险审计。
>
> **〔Iter 38 勘误〕** 本审计的"+20"本身是**静态图离线投影**，已被 §3 真实 A/B 证伪——实战 0/40 局走 canonical
> 大路、`ICE_KEEP=3` 未生效、+20 双冰鉴机制从未激活（详见 `reports/iter36_ab_out/section3_verdict.md` §3）。
> 故"不缩水反略增"在实战层面无意义（no-op 谈不上缩水）。本审计保留作机制记录（大路双冰鉴 +20 在静态图/孤岛
> 条件下成立），**不驱动策略**；flag 已在 Iter 38 回退为关。

## 0. 方法

- **天气重构**：compact.log `F rN w=TYPE` 行 = round N 起天气转 TYPE（compact.py 在天气变化帧发 F 行，rN 是真实变化 round）。重构：round 1..首事件前 = CLEAR（coef 1.0、移动 1000）；之后按事件分段。天气全局（与路线无关），同一局天气序列对山路/大路 walk 同样适用。
- **walker 接入**：`route_planner_eval.walk_route` 加 `weather_seq` opt（默认 None=原 §1 口径，向后兼容）。逐帧应用：移动倍率 `weather_move_multiplier(rt, wtype)`（HEAVY_RAIN+WATER=1350、MOUNTAIN_FOG+MOUNTAIN=1100、余 1000）、鲜度系数 `FRESHNESS_WEATHER_COEF`（HOT 1.5、HEAVY_RAIN 1.3、MOUNTAIN_FOG 1.0）。
- **对比**：每局算 Δ_real（真实天气 大路−山路）vs Δ_clear（无天气上界 +20），shrinkage = Δ_real − Δ_clear。

## 1. 聚合结论（N=67）

| 指标 | 值 |
|---|---|
| CLEAR 上界 Δ | **+20.0** |
| 真实天气 Δ 均值 | **+20.70** |
| Δ 标准差 | 0.73 |
| Δ min / max | +20.00 / +22.00 |
| 缩水均值（Δ_real − Δ_clear） | **+0.70**（正=不缩水，反略增） |
| 鲜度 Δ 均值 | +12.118 |
| 大路净正局 | **67/67** |
| 大路 ≤ 山路局 | **0** |

**判定：稳住——真实天气下大路仍净正，且无单局反劣。+20 不缩水，反而略增 +0.70。**

## 2. 机制：为什么天气不缩水反而略增

两类天气效应，都偏向大路：

**A. MOUNTAIN_FOG 减速山路（Δ 增）**
- 山路 S01-S06、S06-S08 是 MOUNTAIN 边。MOUNTAIN_FOG 下移动倍率 1100（vs 1000）→ 山路多帧 → 多鲜度损耗。
- 大路全是 ROAD，**不受任何天气移动减速**。
- 数据印证：额外帧落在 MOUNTAIN_FOG 的局，shrinkage +1~+2（Δ=+21/+22）。

**B. HOT / HEAVY_RAIN 鲜度同倍惩罚，大路 2 冰鉴更抗（Δ 不缩水）**
- HOT(1.5×)/HEAVY_RAIN(1.3×) 对双方每帧鲜度同倍惩罚。大路多 30 帧 → 多损鲜度。
- **但**：天气降 fresh_no_ice → 好果转坏 crossing 增多。大路 2 冰鉴抵 2 crossing、山路 1 冰鉴抵 1 → 大路好果优势在天气下**扩大**。
- 两效相消：额外帧落在 HOT/HEAVY_RAIN 的局，shrinkage ≈ 0（Δ=+20=clear）。

**净效果**：MOUNTAIN_FOG 增益 + HOT/HEAVY_RAIN 中性 → 均值 +0.70，无任何局缩水。

## 3. 对 §3 真实 A/B 的判决

| 项 | 判决 |
|---|---|
| +20 杠杆天气稳健性 | 🟢 **稳住**：真实天气 Δ ∈ [+20, +22]，67/67 净正，0 反劣 |
| 是否需加天气感知门 | ❌ **不需要**：天气不缩水杠杆，static_planner 现有 `_weather_coef`（读当前帧）足够 |
| §3 预期方向 | 大路收益在真实天气下**不低于** +20（可能略高），可直接跑真实 A/B |
| 时间预算风险 | 🟢 仍安全：大路 ~374-444 帧 < 600，天气减速最多加几帧 |

**结论：§3 真实 A/B 可直接跑，无须先改 static_planner。** 天气审计排除了「大路多 30 帧在天气下缩水」这一最大未知风险。

## 4. 局限

- compact.log 天气变化 round 取自 F 行（状态变化帧）；若天气变化与状态变化不同帧则有数帧延迟（<10%，可忽略）。
- walker 不建模障碍 CLEAR 帧、任务领取帧的天气微差（大路障碍候选点仅 S10，山路 S06/S08/S10——大路占优未计，§1 已述）。
- 冰鉴 post-hoc 最优模型（末尾使用抵 crossing）：与 client `fresh<91 用冰` 实际行为一致（§1 已验证），非过乐观。
- 67 局均同一平台图（samples+2 捷径边）；淘汰赛/决赛换图，天气-路线交互须重新评估（策略须通用读 start）。

## 5. 产出

- `analysis/route_weather_audit.py`（+16 单测，含 `walk_route` weather_seq 接入回归）
- `reports/weather_audit.json`（85KB <100KB）/ `reports/weather_audit.md`
- `route_planner_eval.walk_route` 加 `weather_seq` opt（默认 None=原 §1 口径，10 项 §1 单测全过零回归）
- 全套 430 测试过（127 analysis + 285 client + 18 sim）
