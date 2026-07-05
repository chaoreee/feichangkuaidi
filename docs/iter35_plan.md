# Iter 35 计划 — 山路绕行归因 + 路线鲜度感知修复

> 触发：Iter 34 合入后复核 compact.log 发现 me 实际走山路（S03-S06-S08，MOUNTAIN/BRANCH）而非最优水路（S04-S05-S09，WATER），多损 7.43 鲜度（≈−13.4 分），几乎等于 quality-route 桶鲜度 gap 全部。Iter 34 §1「路线非杠杆」结论已勘误撤销（见 `docs/iter34_route_lever_analysis.md` §勘误）。
> 约束：当前无法重跑真实对战（用户），故 Iter 35 分两段——**先用现有 67 局 reports 做完归因 + stage 代码改动，重跑留到 A/B 阶段一次性做**。

## 0. 现有 reports 充分性确认

每局 `compact.log` 含：Map 拓扑 + me 完整动作日志（MOVE 目标/CLAIM_RESOURCE/USE_RESOURCE/CLEAR/CLAIM_TASK）+ 逐帧状态（含 `on=`/`n=` 节点、`fresh`、`gf`、`w=` 天气、`ots=` 对手任务分）+ 对手稀疏轨迹（≤24 帧，含 `mp` move_progress 可推断持马）。`report.json` 含双方分项分/鲜度轨迹/冰鉴使用/资源。**足以支撑本计划全部归因，无需重跑。**

重跑仅两用途（留到 §4）：①确认 Iter 33/34 真实收益；②新路线策略的 codeagent 真实 A/B 合入门。

## 1. 归因阶段（纯分析，零代码风险，不重跑）

### 1.1 全量路线重建
新建 `analysis/route_audit.py`（纯 stdlib，复用 `parser`/`compact`），对每局 compact.log：
- 从 `A rN MOVE target=SX` 序列 + `F rN n=/on=` 重建 me 完整访问节点序列与每段路线类型/距离；
- 算每段帧数与鲜度损耗（`rules.frames_on_edge` + `FRESHNESS_LOSS_MOVE`）；
- 与 `game_map.time_optimal_path` 对比，输出"实际路线 vs 最优路线"的 Δ帧/Δ鲜度损耗。
- 同法重建对手路线（从 sparse frames 的 `n`/`nx`，标注置信度）。

输出落 `reports/route_audit.json`（<100KB，经 `analysis/sizeguard.py`）+ aggregator 加「## 路线绕行」段（每类对手 me 实际/最优路线偏差均值、绕行频率、Δ鲜度）。

### 1.2 绕行动机归因
对每段绕行（偏离最优路的额外跳），标注动机：
- 领 ICE_BOX（S03/S06/S07 有冰鉴，见任务书 §2.4 资源表）；
- 领 SHORT_HORSE/FAST_HORSE；
- CLAIM_TASK（任务节点不在最优路上）；
- 避障（最优路被障碍挡，`CLEAR`/`SQUAD_CLEAR` 目标节点）；
- 避对手设卡。

### 1.3 净分 ROI 精算
对每局，用 `rules.py` 镜像算"若走最优水路（放弃绕行资源/任务）"的投影终局分，与实际终局分对比：
- 放弃冰鉴：端鲜度 −10、好果多转坏 1 篓（80 阈值）；
- 放弃马：移动帧 +N、鲜度损耗 +N×loss；
- 放弃任务：任务分变化（看是否封顶 180）。
- 得出"绕行净分 = 实际 − 投影不绕行"。若群体均值 < 0 → 绕行负收益，是确凿杠杆。

### 1.4 决策点定位
在 `client/strategy/decision.py` 定位绕行发起点：`_maybe_claim`（资源领取）/`_maybe_task`（任务绕路）/`_plan` 贪心瀑布。确认是哪一步把 me 推上山路。

**1 阶段产出**：`docs/iter35_route_audit.md`（归因报告）+ `analysis/route_audit.py` + 单测。确认绕行是否负收益、定位决策点。**不合并任何策略改动。**

## 2. 修复方案设计（据 §1 结论选一，stage 不合入）

### 方案 A：鲜度感知绕路门（推荐，最小侵入）
在 `_maybe_claim`/`_maybe_task` 的绕路判定加鲜度代价门：
- 绕路额外帧 `extra_frames` × 边路线损耗 → 额外鲜度损耗 `extra_fresh_loss`；
- 资源/任务的边际收益（冰鉴 +10 端鲜度、任务分 Δ、马的速度收益）；
- 仅当 `边际收益 ≥ extra_fresh_loss×1.8 + extra_frames×0.117`（分数地板）才绕。
- 复用 §3.3 ΔEV 地板基础设施（`projection.net_score_delta`，Iter 25 起路线感知鲜度模型已可信）。

### 方案 B：重评 static_planner
若 §1 显示绕行是系统性的（贪心瀑布固有问题，非单点门可修），重评 `ENABLE_STATIC_PLANNER`：在真实图（非 samples）上跑 `plan_route` 看是否选水路。Iter 26–28 sim 中性可能是 samples 图无此绕路模式——需在真实图拓扑上单测验证。

### 方案 C：路线类型感知的 time_optimal_path
当前 `time_optimal_path` 边权=到站移动量（帧数）。加一个 `score_optimal_path`（边权=帧×0.117 + 鲜度损耗×1.8），默认路由改用之。风险：可能全局改变所有路线行为，需 sim 严回归。

**默认选 A**（最小侵入、复用 ΔEV 地板）；若 §1 证明贪心瀑布系统性失效再考虑 B/C。

## 3. 验证阶段（sim 回归门，不重跑）

- 单测：`route_audit` 重建正确性、鲜度感知门触发/拒绝边界、ΔEV 地板交互。
- sim 50 种子回归门：0 STUCK / 0 对账误差 / 分段不回归 / mean 不降。
  - 注：sim 是镜像自博弈 + samples 图，绕行模式可能不重现 → sim 仅作"不破坏 baseline"门，**不验证收益**（收益须真实 A/B）。

## 4. 重跑与 A/B（用户重跑时一次性做）

stage 好的方案（A/B/C）+ Iter 33/34 已合入改动一起，由用户用 codeagent 跑：
1. 新 client（含 iter33+iter34+iter35 改动）对平台真实对手池 N≥30；
2. `python3 -m analysis` 产新 reports；
3. 验证：①Iter 33 交付率（应 96%→~100%）；②Iter 34 好果（应 97→98）；③Iter 35 路线（me 是否改走水路、鲜度是否 82.6→90+、quality-route 桶胜率 0.43→?）；
4. 正向才合入；负则删（§0.5 纪律）。

## 5. 里程碑

| 阶段 | 产出 | 重跑？ |
|---|---|---|
| §1 归因 | `route_audit.py` + `iter35_route_audit.md` + 决策点定位 | 否 |
| §2 方案设计 | stage 代码改动（默认方案 A）+ 单测 | 否 |
| §3 sim 回归 | sim 50 种子不回归 | 否 |
| §4 真实 A/B | codeagent N≥30，验证三段收益，正向合入 | 是 |

**新 session 入口**：从 §1.1 开始（建 `analysis/route_audit.py`），先读 `docs/iter34_route_lever_analysis.md` §勘误 与 `reports/analysis_report.md` 对手类分桶段。
