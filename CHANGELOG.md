# CHANGELOG

本文件记录每轮迭代的能力变化。格式：轮次 / 日期 / 变更摘要。能力矩阵与迭代明细见 `CLAUDE.md`。

## [Iteration 38] - 2026-07-05 — Iter 36 §3 真实 A/B 判负 → 回退 `ENABLE_STATIC_PLANNER` 默认关（纯回退零策略风险）

**触发**：用户上传 `reports/iter36_ab/` 40 局 iter36 平台真实对战 trace（对前 30 名），与 `reports/` 顶层 67 局 iter31 老基线做 §3 真实 A/B（非配对两样本）。`python3 -m analysis reports/iter36_ab/ reports/ --out-dir reports/iter36_ab_out/` 产 `version_ab_report.md`。

### §3 判决 — 负向（详见 `reports/iter36_ab_out/section3_verdict.md`）
- iter36(new N=40) vs iter31(old N=67)：胜率 0.64→0.42（CI[−0.40,−0.00]）、交付率 0.96→0.85（未交付 3→6）、均分 729→649（Δ−80.7 CI[−165.8,+4.5]）、task90 0.97→0.85、8/8 分段回归全 ⚠。
- **混杂排除**：两批对手池分布有偏移（iter36 批 guard-type 多、speed-route 少、expected_win 17 vs 43），但 **27 共同对手 head-to-head** 仍 iter36 劣——交付 96%→88%、胜率 67%→41%、交付均分 762→754。铁证对手：opp=2769（老 11/11 全胜 → 新 1/2）、2629（5/5→0/2）、2735（交付 413 帧 → 未交付 600 帧卡死 S10）。
- **根因①**：大路 `S01→S02→S03→S07→S09→S10→S13→S14→S15` 穿 S10/S14 设卡关隘。6 局未交付中 4 局卡 S10/S14 的 `MOVE_BLOCKED_BY_GUARD`+`MOVING_ACTION_FORBIDDEN` 风暴至 600 帧。Iter 29（在途目标失效回落 `_plan`）+ Iter 33（非 MOVE 动作 8 帧签名冷却）的修复被 static_planner 反复把目标指回 S10 架空——8 帧签名冷却对"唯一通路持久设卡"无效。
- **根因②**：+20 鲜度收益是 sim 自博弈假象（双方都不设卡、不争冰）。真实交付局鲜度 148.1→147.4 持平、task −7、总分 −8——大路多 30 帧转化为卡死风险 + task 绕路丢分，鲜度收益被对抗吞没。`route_weather_audit` 的"大路 +20 不缩水"是在假设无人设卡的逐帧 walker 上得出，缺对抗维度。
- **sim 回归门教训**：Iter 36 §2 sim 50 种子全绿（+30 对称增益/1.000 交付/0 STUCK），但 sim 无进攻设卡→大路永不被封。**sim 回归门对"影响 guard 暴露面的路线类改动"无效**——只能证"不回归"，不能证"对抗下正向"。这是"sim 降为回归门、真实 A/B 升为合入门"纪律的价值兑现。

### Changed — 回退（client/config.py）
- `ENABLE_STATIC_PLANNER = True → False`（默认关，代码保留作 variant）。注释记录 §3 负向判决 + 共同对手铁证 + 根因。
- `CLIENT_VERSION = iter37 → iter38`（标记回退点，区分失败的 iter36 部署）。
- **保留** Iter 33（MOVING_ACTION_FORBIDDEN 风暴修复）+ Iter 34（冰鉴阈值 78→81）——独立于路线、低风险；但本次 §3 因与 static_planner 同包未能单独验证，留待下一轮真实 A/B 单独证。
- 未删 static_planner 代码：§0.5 字面"验证为负则删"，但大路双冰鉴 +20 在无设卡条件下真实存在，guard-aware 改造（`plan_route` 排除对手已设卡 waypoint / 节点级冷却强制绕路）是可期迭代方向，故暂作 flag-off variant 保留。

### Tests / 验证
- sim 50 种子 flag-off 回归门：1.000 交付 / 0 STUCK / 0 对账 / mean 711.9（与 iter36 §2 flag-off baseline 一致，回退干净）。
- 全 452 测试通过（135 analysis + 299 client + 18 scripts）。

### 下一站
- Iter 38 部署 → 平台真实 A/B 单独验 Iter 33/34 + 对手类观测层对账。
- Iter 39+ guard-aware 路线候选 + Iter 33 风暴修复强化（节点级冷却）。

## [Iteration 37] - 2026-07-05 — §3 决策管线加固 + Iter 37 §1 运行期对手类观测层（纯观测，零策略风险）

**触发**：用户已在平台开始 iter36 client 对前 30 名的 §3 真实 A/B（跑数据期间），并行推进两条不依赖 §3 结果的轨道：①让 §3 决策瞬间干净利落；②为 Iter 37 博弈最优提前打观测地基。CLIENT_VERSION iter36→iter37。

### Added — §3 决策管线加固（analysis 侧，纯观测）
- `aggregator.version_ab_report(reports)`：按 `clientVersion` 归一化（`iter36+hash`→`iter36`）分桶的**非配对两样本 A/B**。真实 trace `seed=null` 无法配对（`ab_pair` 仅 sim seed 配对），老/新 client 各对随机对手池打→两独立样本。`old=min(iter)` vs `new=max(iter)`：per-version N/胜率/交付率/均分±CI95/鲜度/好果/交付帧/task90/stuck/未交付；DELTA 两样本均分差 Welch CI（`_welch_diff_ci`）+ 胜率差 CI（`_rate_diff_ci`）；分段回归（任一劣化即不合入）；对手类/运气分布**混杂守卫**（偏移则归因谨慎）；低样本标记。**仅比 `source==platform`**（sim 走 `ab_report` seed 配对，混入无意义）。
- `__main__.collect_reports` 扩三源：`*.report.json`（prio1，最全）/ `*.compact.log`（prio2，parse_compact 还原）/ `match_*.log`（prio0，parse_log），按 matchId 去重保最高优先级。§3 须同框老基线（iter31 N=67，仅存 report.json/compact.log）与新 iter36 trace，故三源皆读。修两个 bug：①`match_*.compact.log` 同时匹配首条 `match_*.log` 分支→按扩展名特异性排序先判；②report.json 源 `compact_trace` 返回空串会覆盖已有 compact.log→仅对原始 match_*.log 派生。
- `__main__._infer_source` 识别 `sim_*` 前缀目录（`reports/sim_iter36_ab/` 原误标 platform 混入真实 A/B）。
- `__main__` 落盘 `reports/version_ab_report.md`（≥2 clientVersion 且 platform 才生成）。

### Added — Iter 37 §1 运行期对手类观测层（client+analysis，纯观测不改动作）
- `client/strategy/opponent_tracker.py` `OpponentTracker`：每帧 `update(world)` 累积对手可观测信号——设卡次数（新出现的对手 active guard 节点计数，己方设卡不计）、用冰次数（ICE_BOX 库存递减量累计，领冰的增量不计）、鲜度 min&last、好果 last、任务 last、交付帧（首次 delivered=True 的 round）。`classify()` 返回 `(class, signals)`，判定阈值镜像 `analysis/opponent_classifier.py`（**SSOT 在 analysis 侧**，client 自包含不可 import analysis；guard>quality>speed 优先级一致）。首帧无 prev 基线不计数、无 opponent 安全跳过。
- `decision._update_projection`：每帧 `opp_tracker.update` + `self.opp_class=classify()`，独立 try（投影失败不影响追踪，追踪失败不影响决策）。
- `main._log_projection`：Projection 行加 `oppClass` 字段（每帧当前估计，末帧即终局）。
- `parser._on_Projection` + compact `_parse_proj`/`_on_Projection`：取末帧 oppClass → `report.projection.runtimeOpponentClass`（compact Proj 行亦加 oppClass，round-trip 一致）。
- `aggregator.runtime_opp_class_agreement`：对账运行期 vs 离线分类（agree/disagree/no_runtime + 不一致样本），`build_analysis_report` 加「运行期对手类对账」段。

### Tests
- 8 项 aggregator 新单测（version_ab_report 多版本/单版本/sim 过滤/低样本/分段回归 + Welch/rate CI + version_key 归一化）；10 项 OpponentTracker 单测（设卡计数/己方不计/用冰递减/鲜度 min&last/交付帧/三分类/无 opponent 安全/guard 覆盖 quality）。
- 全量：135 analysis（+8）+ 299 client（+10）全过。
- **sim 50 种子回归门**：1.000 交付 / mean 741.9 / 0 STUCK / 0 对账失败（与 iter36 baseline 一致——观测层行为中性零回归）。
- **runtime vs offline 对账**：sim 50 局 **50/50 一致**（分类器可信赖，§2 策略切换可接）。

### Misc
- `config.CLIENT_VERSION` iter36→iter37。
- **§2 策略消费（`ENABLE_OPPONENT_CLASS_STRATEGY` + per-class 参数）留 §3 数据回流后定**——per-class 该做什么差异取决于 §3 告知 iter36 之后还输在哪。遵守「纯观测先、验证为正才接策略」纪律。
- 下一站：§3 数据回流 → `python3 -m analysis <新iter36 trace目录> reports/` 产 `version_ab_report.md` → 决策 iter36 合入/回退 flag → 据输在哪定 Iter 37 §2 per-class 策略参数。

## [Iteration 36] - 2026-07-05 — 资源感知路线重评 §1 + §2 stage：大路双冰鉴杠杆确认 +20（马感知 walker）→ 开 static_planner 合入默认（sim 回归门全过）

触发：Iter 35 §5.3 提「马的密度是 quality-route 鲜度 gap 真因」+ `samples/map_config.json` `gameplay.resources`（V4.2-MEDIUM schema）揭示 me 山路漏领 S03/S07 双冰鉴 + S09 快马。`docs/iter36_plan.md` 排「方案 B：资源感知路线重评」。

### Added（§1 纯观测）
- `analysis/route_planner_eval.py`：逐帧 walker（**马感知**——FAST/SHORT 按 `HORSE_DURATION` 帧持续、每帧 tick 含停靠；不复用 `static_planner.project_route` 因其 `path_frames` 恒 `base_move=1000` 无马建模）+ 冰鉴 post-hoc 最优（`+10×N` 封顶 100、抵 crossing，对齐 static_planner）+ 处理站/验核停靠，`core/rules.py` 严格投影终局分。
  - `walk_route`：逐帧模拟移动（buff 决定 base_move）/处理/验核/领取/使用，马策略对齐 client `_maybe_claim`/`_maybe_horse`（无库存才领、无 buff 才用、FAST 优先；buff 活跃期到新马节点领而不使 `HORSE_BUFF_CONFLICT`）。
  - `evaluate_all`：五命名候选（山路/水路/大路/S07混合/S09混合）+ Dijkstra 帧/鲜度最优，算 Δ vs 山路。
  - `static_planner_pick`：构造 world/me/gm/ctx from samples，跑 `plan_route` 真实图选择。
  - `cross_validate_opponent`：从 `reports/*.compact.log` 提取对手 `on=` 节点序列，按资源节点签名分类（大路=S03∧S07、山路=S06∧S08、水路=S04∧S05）。
  - CLI `python3 -m analysis.route_planner_eval` → `reports/route_eval.json`(<100KB)/`route_eval.md`。
- `analysis/tests/test_route_planner_eval.py`：10 项单测（单边帧/损耗手算、马减帧、冰鉴 post-hoc、大路 Δ>0、候选边存在性、frame_optimal=山路、static_planner 选大路、对手签名分类）。

### 结论（§1，纯观测）
- **大路 `S01→S02→S03→S07→S09→S10→S13→S14→S15` 净 +20 vs 山路**：端鲜度 99.2 vs 87.5、好果 100 vs 99、交付 +30 帧；Δ 鲜度 +21 / 好果 +2 / 用时 −3。
- **机制是第 2 冰鉴**（S03+S07 双冰鉴 +10×2 封顶 100），非马/路线类型（FAST 仅覆盖 S09→S10 ~20 帧省 4 帧、路线类型净 +1.8）——Iter 35「马的密度」假设在此图上贡献小。
- **+20 须开 `ENABLE_STATIC_PLANNER`**：baseline `CLAIM_ICE_BOX_KEEP=1` 大路上鲜度到 S07 仍 ~91>81 → 不用冰 → 不领 S07 冰鉴，仅 1 冰鉴（+8）；`STATIC_PLANNER_ICE_KEEP=3` 预囤 2 冰鉴才兑现。
- §1.3：`plan_route` 在真实图选大路（即使无马建模，凭 2 冰鉴+ROAD 低损耗投影分最高）。
- §1.4：对手 `on=` 签名分类 51%（34/67）走大路（低置信，on= 稀疏）；me 山路是少数派（3%）。

### Changed（§2 stage — 合入默认）
- `client/config.py`：`ENABLE_STATIC_PLANNER = False → True`（`STATIC_PLANNER_ICE_KEEP=3` 预囤 2 冰鉴、`STATIC_PLANNER_ICE_USE_BELOW=91`）；`CLIENT_VERSION = "iter34" → "iter36"`。
- §1 确认 +20 杠杆 + §1.3 证 `plan_route` 真实图选大路 → §2 开 flag 既改路线（→大路）又改冰鉴领取（→2 冰鉴），协同兑现 +20。

### Tests（§2 回归门）
- sim 50 种子 A/B（`logs/sim/baseline` vs `logs/sim/tuned --static-planner`，`reports/sim_iter36_ab/ab_report.md`）：
  - MEAN_SCORE 712→742（**+30.0** CI[27.6,32.5]；对称自博弈两侧都走大路都得双冰鉴→对称增益，**非真实收益证据**）。
  - DELIVERY_RATE 1.00/1.00、TASK_90_REACH 1.00/1.00、交付帧 413→445(+32，仍远<600)、PAIRED 52/52/96 ties（对称）。
  - 0 STUCK / 0 对账 / 分段不回归 → **回归门全过**。
- 7 项测 flag-off baseline 行为的单测加显式 `setUp` force-off（原来依赖默认关，flag 默认开后失效）：`test_static_planner.TestDecisionIntegration`、`test_economy.TestEconomy`、`test_advanced.TestTaskDetour`、`test_freshness_resource_race.TestFreshnessRace`/`TestRaceDefaultsOff`；`test_economy` 补 `import config`。
- 414 全过（111 analysis + 285 client + 18 sim）。

### §3 判决（留待 codeagent）
- §3 = codeagent 真实 A/B N≥30 同时验证 Iter 33+34+36（交付率 96%→~100%、好果 97→98、me 改走大路鲜度 82.6→90+/quality-route 桶 W 0.43→?）；正向固化、负则回退 flag（§0.5 纪律）。
- 风险：大路多 ~30 帧，对手设卡/天气恶化时 `_can_afford` 时间守卫兜底回落山路（plan_route 已含 ΔEV 改道门 + 效率门）。

### Added（§1.5 真实天气审计，纯观测）
- `analysis/route_weather_audit.py`：从 `reports/*.compact.log` 重构逐帧天气序列（`F rN w=TYPE`→分段），逐局重跑马感知 walker（山路 vs 大路）算 Δ_real，对比 §1 的 coef=1.0 上界（+20）。
- `route_planner_eval.walk_route` 加 `weather_seq` opt（默认 None=原 §1 口径，向后兼容）：逐帧应用真实天气——移动倍率 `weather_move_multiplier(rt, wtype)`（HEAVY_RAIN+WATER=1350、MOUNTAIN_FOG+MOUNTAIN=1100）、鲜度系数 `FRESHNESS_WEATHER_COEF`（HOT 1.5、HEAVY_RAIN 1.3、MOUNTAIN_FOG 1.0）。
- `analysis/tests/test_route_weather_audit.py`：16 项单测（天气解析、_wtype_at、_weather_summary 截断、audit_game 各天气下大路净正、walk_route weather_seq 回归）。

### 结论（§1.5）
- **大路 +20 在真实天气下不缩水反略增**：Δ_real 均值 **+20.70**（std 0.73，min +20.00 / max +22.00）、缩水均值 **+0.70**、67/67 净正 0 反劣。
- 机制：① MOUNTAIN_FOG 减速山路 MOUNTAIN 边（倍率 1100）→ 山路多帧多损耗，大路 ROAD 不受减速 → Δ +1~+2；② HOT/HEAVY_RAIN 同倍惩罚双方鲜度，但大路 2 冰鉴抵 2 crossing vs 山路 1 → 好果优势扩大（中性）。两效合 → 均值 +0.70。
- 判决：**§3 真实 A/B 无须先加天气感知门**，排除了「大路多 30 帧在天气下缩水」这一最大未知风险，可直接跑。

### Misc
- 详见 `docs/iter36_route_eval.md` / `docs/iter36_weather_audit.md` / `reports/route_eval.json` / `reports/weather_audit.json` / `reports/sim_iter36_ab/ab_report.md`。
- 全套 430 测试过（127 analysis + 285 client + 18 sim）。

## [Iteration 35] - 2026-07-05 — 路线绕行归因：证伪「路线是鲜度杠杆」（Iter 34 勘误自身勘误），不 stage 策略改动

**触发**：Iter 34 合入后复核 compact.log，§1「路线非杠杆」结论已勘误撤销，roadmap 排「Iter 35 山路绕行归因 + 路线鲜度感知修复」。本轮用 67 局 compact.log 全量重建 me 实际路线做硬核算。详见 `docs/iter35_route_audit.md`。

### Finding — A. Iter 34 勘误自身又勘误一次（`on=` 误读）
- compact.log 中 `n=` = me 节点、`on=` = 对手节点（`client/main.py:326,333` 的 `node=`/`oppNode=`）。Iter 34 勘误误把 `on=` 当 me 途经节点，得出 me 走 `S01→S02→S03→S06` 的错误路线（S02/S03 实为对手节点）。
- 实际 me 走 `S01→S06` 直连山路边（`S01-S06:44:M`，79 帧）。修正后绕行成本 **+7 帧 / +4.895 鲜度损耗**（非勘误的 +64/+7.43）。

### Finding — B. 绕行是净正收益（+147 中位），不是杠杆
- 新模块 `analysis/route_audit.py`（复用 `core.rules` + `core.pathfind` + `analysis.compact.parse_compact` + `analysis.opponent_classifier`）重建 67 局路线。**64/67 局 me 走固定山路绕行 `S01→S06→S08→S10→S13→S14→S15`**（与对手类无关、跨局常量）。
- 绕行动机：S06 领 ICE_BOX + S08 领 SHORT_HORSE（每局都为冰鉴+马绕行；任务非主因）。主动选择、非障碍逼路（r1 即 CLEAR S06/SQUAD_CLEAR S08，水路从无 CLEAR）。
- ROI 投影（`rules.py` 镜像，放弃绕行资源/任务）：冰鉴 +10 抵消多损的 4.9（端鲜度 wash 83.36 vs 83.02），另赚 3 off-route 任务（+105 任务分 +40 送达分）+ 马。**64/64 交付局绕行净增益 > 0，均值 +93、中位 +147**。

### Verdict — C. 方案 A 证伪、不 stage 策略改动
- §2 方案 A（鲜度感知绕路门）**证伪、不合入**：会阻断 +147 的绕行（为省 8.8 鲜度分放弃 +145 任务/送达分），方向相反。方案 B（重评 static_planner）方向正确（联合优化器正是会选此绕行的工具）但留待 Iter 36 真实图 A/B；方案 C 不需要。
- **Iter 35 不 stage 任何策略改动**，遵守 §0.5 纪律（验证为负则删）。仅新增纯观测分析模块，client/strategy 零改动、CLIENT_VERSION 不 bump。
- quality-route 鲜度 gap 真因是**马的密度**（对手全程 FAST_HORSE、total_loss 13.79；me 仅 1 匹 SHORT_HORSE、total_loss 26.64），非绕行决策——提上 Iter 36（Iter 34 §4 候选 A，须真实 A/B N≥30）。

### Tests — D. 验收
- `analysis/tests/test_route_audit.py` 11 项单测（Map/最优路 322 帧 16.98 损耗、me 路线 329 帧 21.875 损耗、Δ +7/+4.895、动机标注、ROI 净正、聚合/segment、对手路线低置信）。analysis **101 全过**（90+11）。
- 全量回归：analysis 101 + client 285 + sim 18 = **404 全过**。sim 5 种子 sanity（1.000 交付 / 0 STUCK / 0 对账）——无策略改动故零回归。

### Misc — E. 产出
- `analysis/route_audit.py` + `analysis/tests/test_route_audit.py`
- `reports/route_audit.json`（82.9KB <100KB）/ `reports/route_audit.md`（67 局归因 + 按对手类聚合）
- `docs/iter35_route_audit.md`（归因报告）

## [Iteration 34] - 2026-07-05 — quality-route 鲜度杠杆证伪 + 冰鉴阈值保鲜修复（弱优于，无条件合入）

**触发**：Iter 32.5 N=67 群体归因 quality-route 桶（N=30, W=0.43, opp 鲜度 93.2 vs me 82.6, gap +10.5）→ roadmap 排「Iter34+ 静态最优：Phase B 静态规划器路线重选」。本轮用真实地图拓扑 + 全量鲜度模型做硬核算**证伪路线杠杆**，定位真正根因，落地一个数学弱优于的冰鉴阈值修复。详见 `docs/iter34_route_lever_analysis.md`。

### Finding — A. 路线选择不是鲜度杠杆（roadmap 修正）
- 取真实 compact.log Map 拓扑（15 节点 23 边），Dijkstra 三准则独立求解：
  - 时间最优（min frames）/ 鲜度最优（min loss）/ 分数最优（min score-cost）**三路完全重合**：`S01→S02→S04→S05(W)→S09(W)→S10→S13→S14→S15`，322 帧 / 16.98 鲜度损耗。
  - 时间最优路已走 WATER 边——WATER 同时是 `ROUTE_TIME_COEF` 最低（最快）与 `FRESHNESS_LOSS_MOVE` 最低（最保鲜）的路线类型。**本图不存在"更长的低损耗替代路"**。
- **修正 roadmap**：Phase B 静态规划器（`ENABLE_STATIC_PLANNER`，默认关）核心是鲜度感知路线重选，前提已被证伪。Iter 26–28 sim A/B 中性的真正原因是真实图本身无廉价鲜度路线，非仅 samples 图。**静态规划器是 quality-route 鲜度 gap 的错误工具，Iter 34 不开启，后续不再为其投入 A/B。**

### Finding — B. 真正根因是冰鉴时机（操作层，非路线层）
- 代表性 quality-route 败局：同路同天气，我方 total_loss=26.64 vs 对手 13.79（差一倍）。端鲜度公式 `end=100−loss+10×ice`（任务书 §3.3.1：冰鉴 +10、好果转坏不可逆）**与冰鉴时机无关**——gap 不在端鲜度，在 MIN 鲜度。
- 我方 MIN 77.26（78-阈值在跌 80 后才用冰鉴，80 已转坏 → 2 坏果）；对手 MIN 85.28（80 之上用，只跌 90 → 1 坏果）。冰鉴在 78-阈值下只能护 70，而本图端鲜度 83 ≥ 70，70 本不会触底 → **冰鉴被浪费**。

### Changed — C. `ICE_BOX_USE_BELOW` 78 → 81（弱优于，无条件合入）
- `config.py`：`ICE_BOX_USE_BELOW = 81.0`（+ 注释说明 80 阈值保护机理）。在跌破 80 好果转坏阈值前用冰鉴（80.x→90.x），端鲜度不变但 MIN 鲜度从 ~77 抬到 ~81，80 阈值不再触发 → 救回 1 篓好果（+1.8 分）。
- **弱优于证明**（任务书规则下）：端鲜度 F=100−L+10。中损耗区间（80≤F<90，真实图 F=83.36 正属此）78 在跌 80 后用、81 在跌 80 前用 → 81 严格省 1 坏果；其余区间（F≥90 或 F<80）两者坏果数相同。**永不更差，真实图严格省 1**。与 Iter 25/29/33 同属"弱优于/bug-fix 纪律无条件合入"，非阈值赌博。
- 不取 91（`STATIC_PLANNER_ICE_USE_BELOW`）：91 在 F<90 路线与 81 等价（90 终被跌），却在低损耗路线过早触发浪费库存；81 仅在鲜度实跌向 80 时触发，更保守。
- `CLIENT_VERSION` iter33→iter34。

### Tests — D. 验收
- `tests/test_economy.py` 新增 `test_ice_box_fires_just_above_80_threshold`（freshness=80.5 触发）+ `test_no_ice_box_at_82`（82 不触发）。client **285 全过**（283+2）。
- sim 50 种子回归门：**1.000 交付 / 0 STUCK / 0 对账误差 / mean 747.8（=Iter33 基线零回归）**。sim 中性是 no-op 而非无效——sim 鲜度损耗更高（端鲜度 ~75.6 < 80，§4.4 残留偏差），80 终被跌穿、81 与 78 等价；**收益仅在真实图（端鲜度 83 ≥ 80）显现**。这正是 sim 无法验证、须真实 A/B 的部分，但弱优于性质保证不劣化。

### Misc — E. 残留 gap 与 Iter 35+ 候选
- 81-阈值救回 1 好果（97→98）仍差对手 1（98 vs 99），且对手端鲜度 96.21 vs 我方 83.36（−13）无法仅靠冰鉴时机解释（端鲜度时机无关）——疑似对手更密集用马（降移动帧/鲜度损耗）或我方绕路领资源（S07 绕路 +33 帧）。受 sparse 对手轨迹所限无法确证。
- Iter 35 候选（须 codeagent 真实 A/B N≥30，不预合入）：A. 马匹密集领取；B. 冰鉴/马绕路 ROI 评估；C. 多冰鉴囤积（`CLAIM_ICE_BOX_KEEP` 1→2）。

## [Iteration 33] - 2026-07-05 — 真实对战基线 P0.2：修复 MOVING_ACTION_FORBIDDEN 重试风暴致 3 局未交付（无条件合入）

**触发**：Iter 32.5 codeagent 跑出 N=67 真实对战基线（`reports/`，clientVersion=iter31，4W→43W/67=64% 胜率，交付率 96%）。群体归因定位**3 局未交付（4%）**为最大失分点（每局 me≈67 必负）。三局 compact trace 同根因：到达对手设卡关隘 S10 后进入 `WAITING` 态，`_keep_moving` 回落 `_plan` 连发非 MOVE 节点动作，全被 `MOVING_ACTION_FORBIDDEN` 拒、连发成风暴烧光交付窗口：
- `032341`：BREAK_GUARD×52 + USE_RESOURCE(ICE_BOX)×287
- `035502`：BREAK_GUARD×54 + USE_RESOURCE(ICE_BOX)×201
- `034523`：FORCED_PASS×60 + RUSH_PROTECT×180

与 Iter 25（CLAIM_TASK+OBJECT_BUSY 风暴）、Iter 29（MOVE_BLOCKED_BY_GUARD 死锁）同源——拒绝反馈未被消费成"不重发"。`DELIVER`/`VERIFY_GATE` 不受 `MOVING_ACTION_FORBIDDEN` 影响（WAITING 态仍可交付/验核），故仅针对该码的 4 类动作冷却。

**修复（Iter 25/29 拒绝冷却模式的泛化，零策略风险）**：
- `config.py` 新增 `REJECT_ACTION_COOLDOWN_ROUNDS=8`。
- `DecisionEngine` 新增 `_action_cooldown: (action,target,resource)->expiry`；`_apply_rejection_feedback` 对**非 MOVE 动作 + MOVING_ACTION_FORBIDDEN** 按签名冷却（USE_RESOURCE 区分 ICE_BOX/HORSE 不误伤）。
- 新增 `_action_sig`/`_action_cooled` helper；4 个风暴发起点加冷却门——冷却中跳过 → `_plan` 落到 `_advance`(MOVE) 重路由绕行：
  - `_freshness_rescue`（ICE_BOX 风暴源）
  - `_maybe_rush_protect`（RUSH_PROTECT 风暴源）
  - `_maybe_bounty`（BREAK_GUARD 风暴源，跳过被冷却的相邻悬赏候选，保留 MOVE 靠近分支）
  - `_breakthrough`（FORCED_PASS/BREAK_GUARD/CLEAR 风暴源，逐替代动作冷却检查，全冷却则回落 MOVE）
- `_window_card`：MOVING/WAITING 态只出 ABSTAIN（安全弃权，不烧资源/不触 MOVING_ACTION_FORBIDDEN）。

**纪律**：纯 bug 修复（拒绝反馈消费），不改策略、不开 flag、不涉阈值；与 Iter 29 P0 同属"修交付卡死"无条件合入类。`CLIENT_VERSION` iter31→iter33。

**验收**：391 单测全过（283 client[273+10 新 `test_action_cooldown.py`] + 90 analysis + 18 sim）；sim 50 种子回归门——DELIVERY_RATE 1.000、0 STUCK、对账 ok=100 mismatch=0、交付帧 mean 455.4 / 分 mean 747.8 均与基线一致零回归（镜像自博弈无设卡故路径不触发，验证冷却逻辑不破坏 baseline）。预期真实对战转化 3 局未交付→交付（+~2000 分、潜在 +3 胜），抬地板 729→~760。

**未做（下一轮）**：群体归因另两条主线——① quality-route 桶（N=30, W=0.43, opp 鲜度 93.2 vs me 82.6）的鲜度杠杆（Phase B 静态规划器，需 codeagent 真实 A/B N≥30）；② guard-type 桶（N=9, W=0.67, me 528 分偏低）归因。均需用户用 codeagent 跑真实 A/B 验证。

## [Iteration 32] - 2026-07-05 — codeagent 真实对战基线准备：对手策略分类器 + analysis 群体归因段（对手类分桶，纯观测零策略风险）

落地 `docs/iteration_loop_design.md` §0.5（Iter 32 框架升级）。codeagent 自动对战闭环取代手动收割：Claude Code 改代码 → push → 内网 codeagent 拉取 → 对平台真实对手群体自动跑一轮 → 收 `match_*.log` → `analysis` 解析聚合 → Claude 读**群体归因报告**定下一轮（codeagent 自收集自调 analysis，**repo 侧无需契约**）。本轮 repo 侧交付**对手策略分类器**与**群体归因段**，使新 reports 回流后 `analysis_report.md` 头部按对手类分桶看胜率/均分/分项差——为 Iter 33+ 静态最优 A/B 提供归因主线，把分析器从"单局时间线导向"转向"群体归因导向"。**纯观测/分析，零策略风险，不改任何运行期决策，client 零改动**。

### Added — A. 对手策略分类器（`analysis/opponent_classifier.py`，新模块）
- `classify_opponent(report) -> {class, signals}`：用 P1-A 已抽到的对手轨迹/用冰/设卡，对每局对手打类标签。三类互斥全覆盖，优先级 **guard > quality > speed**：
  - **guard-type**：`oppGuards` 非空（对手至少设卡一次）——进攻性设卡是主动强信号，覆盖路线型归类。
  - **quality-route**：`freshnessEnd ≥ 85` 且（`goodFruitEnd ≥ 95` 或 `iceUsed` 非空）——鲜度积累型。
  - **speed-route**：其余（快交付/低鲜度型）。
  - 旧 trace 无对手鲜度且无设卡 → `unknown`（不崩）。
- 阈值取物理含义（85 = 一次好果→坏果跨越线之上、95 = 实质量满），**不扫参数**；`signals` 记 freshnessEnd/goodFruitEnd/iceUsedCount/oppGuardCount/oppDeliverFrame/oppTaskBase 供归因下钻。
- `annotate_opp_class(report)`：幂等注入 `classification.opponentClass` + `oppClassSignals`。

### Added — B. aggregator 群体归因段（`analysis/aggregator.py`）
- 新增 `_opp_class_section(reports)` + `_opp_class`/`_opp_total`/`_opp_freshness`/`_opp_good_fruit` 等访问器。
- `build_analysis_report` 在「总体」段后加「## 对手类分桶（Iter 32 群体归因，假设级）」段：每类 N/胜率/me 均分/opp 均分/鲜度 me-opp gap/好果 me-opp gap/我方交付帧 + 跨类归因一句话（最低/最高胜率类）。
- `build_index` 每条加 `opponentClass`，便于按类过滤下钻。

### Added — C. 接线（`analysis/__main__.py`）
- `collect_reports` 后对每局调 `annotate_opp_class`，使单局 report.json / index / 聚合报告共享同一标签。

### Added — D. 体积守卫（`analysis/sizeguard.py`，新模块）
- 确保每个产物文件 <100KB（`MAX_FILE_BYTES=100_000`）。只在**写出时**对序列化产物有损裁剪；喂给 aggregator 的内存 Report 保持全保真（聚合统计不受影响）。小报告原样落盘、零开销。
- `fit_report`：超预算时按序——① **保信息合并**（连续相同 `failures.rejected`/`decisionTimeline`/`canAffordBlocked` 合并为一条带 `count`+`firstFrame`/`lastFrame`，信息不丢，如 vs2735 的 224 次 `MOVE_BLOCKED_BY_GUARD` → 1 条 count=224）→ ② **有损封顶**（逐级收紧 head/tail，插 `_ELIDED` 标记注明丢了多少）→ ③ 丢 `trajectory.opponent.frames` → ④ 兜底 timeline 置标。
- `fit_json_list`：index.json 等 JSON list 超预算时保前 N 条 + 一条 `_truncated` 标记（合法 JSON）。`fit_text`：md/compact.log 超预算时截断附尾部标记（不切断多字节字符）。
- `assert_dir_under_limit`：落盘后扫 out_dir，超限文件告警；CLI 末尾打印 `sizeguard: all artifacts under 100000-byte limit`。
- `__main__` 全部写盘点（report.json / compact.log / index.json / analysis_report.md / ab_report.md / timelines.md）接入守卫。

### Config
- **不 bump `CLIENT_VERSION`**（零运行期变化，纯分析侧）。

### Tests
- 新增 `analysis/tests/test_opponent_classifier.py`（14 项）：三类各例 + guard 覆盖 quality 优先级 + 鲜度边界 84/85 + 旧 trace 降级 unknown + signals 填充 + annotate 幂等 + index 字段 + 分桶段三类 N/胜率 + unknown-only + analysis_report 含分桶头。
- 新增 `analysis/tests/test_sizeguard.py`（15 项）：小报告原样不拷贝 + 不 mutate 输入 + 超预算达标 + count 保信息 + timeline 合并 + 封顶插 _ELIDED 保头尾 + 合法 JSON + 兜底 + JSON list 截断 + text 截断/多字节不切断 + 目录自检。
- 全量 381 单测过（273 client + 90 analysis[61+14+15] + 18 sim 零回归）。

### Verification
- sim 200 局回灌（`logs/sim` → 临时 out-dir）：`analysis_report.md` 出现「对手类分桶」段、report.json `classification.opponentClass` 与 `oppClassSignals` 注入、index.json 每条带 `opponentClass`、对账 0 误差、ab_report/timelines 正常。镜像自博弈无设卡→196 speed-route / 4 quality-route（预期）。
- 体积守卫：`python3 -m analysis logs/` 落盘后 `find reports -type f -size +100k` 为空，最大文件 index.json 95KB（200 条目，未触发裁剪即自然达标）；CLI 末尾打印 `sizeguard: all artifacts under 100000-byte limit`。
- 阈值标「假设级」（N<30），Iter 33+ codeagent 真实数据回流后校准。

### Next
- 用户在内网用 codeagent 拉 `loop_engr` 分支对平台真实对手群体跑首轮基线（iter31 富化版 client）→ 收 `match_*.log` 回流 `logs/` → `python3 -m analysis logs/<dir>` 产出含分桶段的 reports。
- Iter 33+ 静态最优：开 `ENABLE_STATIC_PLANNER` / 调冰阈值 / 鲜度感知选路，codeagent 真实 A/B（new vs old client，N≥30）验证地板 755→770。

## [Iteration 31] - 2026-07-04 — beat_top10 P1-A：分析器数据补全（client trace 富化 + parser 抽取 + aggregator 落盘，纯观测零策略风险）

落地 `docs/iteration_loop_design.md` P1-A。打败前十名的 P2/P3 设计强依赖"对手凭什么鲜度 88–93"等归因，但当前 `reports/` 无法回答：协议层对手信息几乎全可见（`inquire.players[]` + `over.players[].scoreDetail`），缺口在 **client 不记 + parser 不抽**。本轮把对手分项分/设卡/资源/逐帧轨迹写进完整 trace 并解析入库，使 `report.json` 携带双方分项、`analysis_report.md` 出现对手分项与设卡段。**纯观测/分析，零策略风险，不改任何运行期决策**。

### Added — A. client 富化（`client/main.py`）
- `_log_frame` 补对手字段（均为 inquire 已有、零推断）：`oppBad`/`oppVerified`/`oppMoveProg`/`oppNext`/`oppGuardAP`/`oppResources`。
- 新增 `_log_guards(logger, rnd, world, engine)`：每帧设卡集合变化时记一行 `Guards round=r guards=[node:owner:defense|...]`（owner=队伍 id）。对手进攻性设卡的唯一可观测来源（match 4 的 S10 设卡由此首次被记录）。sig 缓存于 `engine._guards_sig` 去重控体积；无设卡时发空 `guards=[]` 关闭区间。
- `_log_over` Score 行补 `scoreDetail=[k=v|...]`（双方分项 delivery/tasks/time/goodFruit/freshness/bounty/penalty/total）。
- 新增 `_dict_token`/`_resources_token`：dict 序列化为方括号管道列表，绕开 trace `_parse_fields` 的 `, ` 切分（原生 `str(dict)` 含 `, ` 会破坏解析）。

### Added — B. parser 抽取（`analysis/parser.py`）
- `_final_score` 去 stub：新 `_parse_score_detail` 把 Score 行 `scoreDetail`（list / `[k=v|...]` 串 / 单条 `k=v` 三态）还原为 dict，填双方 `delivery/task/time/goodFruit/freshness/penalty`；`task` 兼容协议 `tasks`（复数）与 sim `task`（单数）；`bounty` 优先 `bountyScore` 字段回落 sd。旧 trace 无 sd → 分项全 None（向后兼容）。
- `_on_Guards`：解析 `Guards` 行，按 `owner != team_id` 判对手设卡，追踪 `node→{firstFrame,lastFrame,defense}` 区间，消失时 finalize 为 `opp_guard_episodes`。`build_report`：`oppGuards` = episodes（附匹配 BREAK_GUARD 的 myResponse/cost）；旧 trace 无 Guards 行则回落 `_on_Action` BREAK_GUARD 派生记录（保旧测试不回归）。
- `_on_Frame` 扩 opp 字段：`trajectory.opponent.frames`（稀疏列表，仅任一字段变化时记一条，≤24 条溢出保首12末12，短键 `r/n/s/ts/b/vf/mp/nx/ga/rs`）+ `freshnessMin`/`badFruitEnd`/`verifyFrame`/`iceUsed`（ICE_BOX 库存递减推断）+ `tasks.opp.claimed`（oppTask 上跳轨迹）。`delivery.opp` 加 `verifyFrame`。
- `SCHEMA_VERSION` 1→2。

### Added — C. aggregator（`analysis/aggregator.py`）
- `opp_score_components`：与 `me_score_components` 对称，直接读 `finalScore.opp` 分项求均值（trace 经 scoreDetail 携带，不 recompute）——首次能量化"对手赢在哪个分项"。旧 trace 无 sd → n=0。
- `opp_guard_stats`：`(episode_count, games_with_guard, blocked_me_frames)`；blocked_me_frames = ∑ `failures.rejected` 中 `MOVE_BLOCKED_BY_GUARD`。
- `opp_resource_stats`：对手冰鉴使用总数 + 鲜度 min/end 序列。
- `build_analysis_report` 新增「对手分项与设卡（P1-A）」段：`OPP_SCORE_COMP`/`OPP_GUARD`/`OPP_ICE_USED`/`OPP_FRESHNESS`。
- `SUPPORTED_SCHEMA` 1→2。

### Changed — D. sim 对齐（`scripts/sim_engine.py`）
- `_player_over` 加 `scoreDetail`（由 `_score_detail(p)` 派生，键 `task`→`tasks` 对齐协议），使 sim trace 携带分项、sim report 亦有 opp 分项。

### Changed — compact（`analysis/compact.py`）
- `_score_fields` 把 scoreDetail list 渲染回 `[k=v|...]`（防 `"det=%s" % list` 带空格破坏 `parse_compact`）；`_parse_score_detail` 三态兼容使 compact `det=` 透传后 `finalScore` 分项与 parser 0 误差。

### Config
- `CLIENT_VERSION` iter29→iter31（trace 格式变化）。

### Tests
- 新增 `analysis/tests/test_parser_opp_fields.py`（10 项）：scoreDetail 填分项/`task` 单数兼容/旧 trace 降级；Guards 行设卡区间/己方卡不计/ BREAK_GUARD 响应附挂/旧 trace 回落；opp frames 稀疏截顶/resources+task 跳变/字段入 frames。
- 扩 `analysis/tests/test_aggregator.py`（+4 项 `TestOppStatsP1A`）：opp_score_components/legacy 跳过/opp_guard_stats/P1-A 段出现。
- 扩 `analysis/tests/test_compact.py`：scoreDetail round-trip（`det=` 透传后双方分项 0 误差）；`trajectory.opponent` 比对收紧到 compact 可还原的标量字段（frames/iceUsed 等为 parser 侧富化，compact 有损不携带）。

### Verification
- 全量 352 单测过（273 client + 61 analysis[42+10+5+4] + 18 sim 零回归）。
- sim 回灌：report.json `finalScore.opp.{delivery,task,time,goodFruit,freshness}` 非 null、`trajectory.opponent.frames` ≤24、`oppGuards` 结构正确、`analysis_report.md` 出现「对手分项与设卡（P1-A）」段、对账 0 误差。
- 旧 trace（iter30 及以前）优雅降级：分项 null、oppGuards 回落 BREAK_GUARD 派生、`n=0`。
- 尺寸预算：report.json 正常局稳在 ~5–6KB（frames 段 ≤24 条增量 ≤~1.5KB）。

## [Iteration 30] - 2026-07-04 — beat_top10 P1-B：精简 trace 派生（数据回流通道，纯观测零策略风险）

落地 `docs/iteration_loop_design.md` P1-B。原始完整 trace ~880KB–1.16MB/局、`.gitignore` 不入库无法上传 → 我只能读 `reports/`，核心数据到不了手。本轮把完整 trace **派生**为事件驱动紧凑格式（~6–9KB/局纯文本 / ~1.4KB gzip+base64），落 `reports/<matchId>.compact.log` 入库，使我 pull 后能直读、彻底绕开上传瓶颈。**client 零改动、零策略风险、不 bump `CLIENT_VERSION`**。

### Added
- 新增 `analysis/compact.py`：
  - `compact_trace(source)`：完整 trace（路径或文本）→ 精简文本。事件驱动——帧状态仅变化时记 `F`、动作仅 (action, 关键参数) 变化时记 `A`、连续相同拒绝/canAfford 合并（`REJ x224`/`CAB x<n>`）、逐帧 Projection/Eta 丢弃只留末帧摘要 `Proj`/`Conf`/`MidGap`、轨迹摘要 `Traj`。多局文件按局分块（`---` 分隔）。
  - `parse_compact(text)`：精简首块 → 与 `parser.parse_log` 同 schema 的 `Report` dict。复用 `parser` 的 `_final_score`/`_task_block`/`_segments`/`_luck_class` 组装，防 schema 漂移；waitingStuck 由状态/节点变化推算（与 parser 逐帧计数等价）。
  - `to_b64`/`from_b64`：gzip+base64（~1.4KB/局，供聊天粘贴）。
  - 独立 CLI `python3 -m analysis.compact <logfile> [--b64]`。
- 新增 `docs/compact_trace_format.md`：一页格式 spec（行类型枚举 + 字段语义 + 还原保真度/已知近似），供 compact parser 与人阅读参考。
- `analysis/__main__.py`：`parse_log` 后追加 `compact_trace` 写 `reports/<matchId>.compact.log`；新增 `--b64` 开关打印 gzip+base64 到 stdout（聊天粘贴用）。

### Tests
- 新增 `analysis/tests/test_compact.py`（5 项）：
  1. `test_roundtrip`：完整 trace → `compact_trace` → `parse_compact` 与 `parse_log` 关键字段 0 误差（matchId/outcome/finalScore 双方/delivery/oppGuards/失败模式计数/trajectory/projection/classification/resources/tasks）。
  2. `test_size_budget`：精简纯文本 < 10KB/局；b64 < 4KB。
  3. `test_b64_roundtrip`：`from_b64(to_b64(x)) == x`。
  4. `test_rejection_collapse`：224 次连续相同拒绝 → 1 行 `REJ x224`，`parse_compact` 还原 224 条；与 `parse_log` 计数一致。
  5. `test_legacy_trace`：旧 trace 缺 oppState/oppTask/weather 等 P1-A 字段 → 精简格式优雅降级，`parse_compact` 仍重建 Report，缺字段 None（与 parser stub 一致）。

### Verification
- 全量 338 单测过（273 client + 47 analysis[42+5] + 18 sim）。
- 回灌 sim 50 局（每文件多局追加）：每局精简 ~2.9KB（< 10KB 预算），`parse_compact` roundtrip 关键字段 0 误差（仅 `decisionTimeline` 条目数因动作折叠偏少——非关键字段，spec 已记已知近似）。
- P1-A（Iter 31）富化字段（oppResources/Guards/scoreDetail）一旦进入完整 trace，精简格式自动透传，无需改 compact。

## [Iteration 29] - 2026-07-04 — beat_top10 P0：修复被对手设卡卡死的未交付 bug（无条件合入）

落地 `docs/iteration_loop_design.md` P0。vs2735 那局我方 60 分未交付——对手进攻性设卡封 S10、`MOVE_BLOCKED_BY_GUARD` 连拒 224 帧（帧 262–485），全程未发 `BREAK_GUARD`/`FORCED_PASS`。根因：`_keep_moving`（MOVING/WAITING 态短路返回）重发 `MOVE(next_node_id)` 不检查在途目标是否已被对手设卡 / 在冷却期，而拒绝反馈写入 `_cooldown` 却无人读取 → 死锁卡至终局。与 Iter 8（卡 S14）同源，Iter 8 只修"无在途目标"分支，P0 补"在途目标失效"盲区。**bug 修复，无 flag、无阈值，无条件合入**。

### Changed
- `client/strategy/decision.py` `_keep_moving`：重发 MOVE 前校验在途目标是否失效；失效则丢弃在途目标回落 `_plan` 全量重规划（`_advance` 绕行 / `_breakthrough` FORCED_PASS/BREAK_GUARD）。docstring 更新。
- 新增 `_in_transit_target_blocked(world, me, nxt)`：复用既有 `_is_cooldown`（decision.py:312-313）与 `NodeState.active_guard_owner()`（world_state.py:115-120）——在节点冷却期 **或** 被对手设卡（active guard owner != 我方）即判失效。与 `_blocked_nodes` 同一组条件，只判单个在途目标；己方设卡不挡己方（owner==me.team_id → 续行不变）。
- `client/config.py`：`CLIENT_VERSION` iter25 → iter29（运行期行为变化：被设卡时改道）。

### Tests
- 新增 `client/tests/test_keep_moving_guard.py`（5 项，仿 `test_breakthrough_fruit.py`）：
  1. 在途目标被对手设卡 → 绕行 MOVE(SA)（非续行 MOVE(SG)）。
  2. 在途目标在 `_cooldown` → 同上绕行（证冷却触发重规划；拓扑加 SA 备路使重规划产生绕行而非 `_breakthrough` 兜底 MOVE）。
  3. 在途目标畅通 → 续行 MOVE(SG)（防回归）。
  4. 在途目标被己方设卡 → 仍 MOVE(SG)（己方卡不挡己方）。
  5. 无在途目标 + WAITING → 重规划 MOVE(SG)（既有行为，防回归）。
- 全量 client 单测 273 过（268 + 新增 5）。

### Verification
- sim A/B 50 种子 baseline：mean 747.8、交付帧 455.4、交付率 1.000、0 STUCK、对账 0 误差——**0 回归**。镜像自博弈无进攻性设卡（`ENABLE_OFFENSIVE`/`ENABLE_CONDITIONAL_GUARD` 默认关）故 P0 路径不触发，确认未激活时零影响；激活时（被设卡）正确回落 `_plan` 绕行/突破。
- 预期收益：vs2735 那局 60 → ~755（消除白送未交付），4/10 → ≥5/10。须真实 trace 复核被设卡时是否正确选 FORCED_PASS（时间税可负担）vs 绕行 vs BREAK_GUARD。

### Misc
- 风险/回退：单 `git revert`，无 flag 依赖。`_plan` 轻量（Dijkstra + 机会式），单帧 <500ms；`REJECT_BLOCK_ROUNDS=4` 冷却限频天然防高频重算。
- 下一轮 Iter 30：P1-B 精简 trace 回流通道（`analysis/compact.py`，client 零改动）。

## [Iter 29+ 规划] - 2026-07-04 — 打败前十名 P0–P3 蓝图定稿（设计文档，未实现）

基于 10 局对平台前十名真实报告（`reports/`，N=10 假设级，4W/6L）定稿下一步迭代蓝图。**无代码改动**，仅设计与规划文档。

### Added
- `docs/iteration_loop_plan.md`：总览——诊断（我方固定点 755、胜负 100% 由对手鲜度决定、分隔线 oppFr~82）、根因（`_keep_moving` 在途目标被设卡不回落 `_plan` → 224 帧卡死未交付）、P0–P3 按 ROI/置信度排序。
- `docs/iteration_loop_design.md`：P0–P3 详细设计与实现（file:line 精确 + 代码 + 单测 + 验收 + 排期 + 风险登记）。
  - **P0** 修设卡卡死（`_keep_moving` 校验在途目标失效→回落 `_plan`，5 项单测，无条件合入，预期 +1 胜）。
  - **P1-A** client trace 富化（opp 库存/设卡/scoreDetail）+ parser 抽取 + aggregator 落盘对手分项分。
  - **P1-B** 精简 trace（`analysis/compact.py` 从完整 trace 派生事件驱动紧凑格式 ~6–9KB/局落 `reports/`，绕开"原始 trace 880KB 无法上传"瓶颈；client 零改动；gzip+b64 ~1.4KB/局可选）。
  - **P2** 鲜度质量积累（抬地板 755→770，P1 归因驱动选 A/B/C/D 分支）。
  - **P3** denial（设卡/破卡/争抢，真实 trace A/B，sim 镜像自博弈无法验证博弈层）。

### Changed
- `CLAUDE.md`：新增「Iter 29+ 规划」bullet（10 局证据 + P0–P3 排期 + 根因）、§6 Roadmap 加 M10、进度行"下一步"指向 `iteration_loop_design.md`。

### Misc
- 排期：Iter29 P0 → Iter30 P1-B → Iter31 P1-A → Iter32 取 reports（含 `*.compact.log`）→ Iter33 归因选分支 → Iter34 P2 → Iter35 P3 → Iter36+ 校准。
- 铁律不变：flag 默认关、阈值合入须真实 trace N≥30、sim A/B 50 种子 CI 正向 + 分段不回归、策略通用（读 `start`、决赛换新图）。

## [Iteration 28] - 2026-07-04 — Phase B v2 + ΔEV 每帧效率门（机制验证成功消除 v2 回归，samples 上仍中性，flag 保持关）

落地 `docs/calibration_v1.md` §7「下一步候选①」。v2 失败根因：`plan_route` 改道门是**纯绝对增益门**（`gain ≥ STATIC_PLANNER_MIN_ROUTE_GAIN`），放行了投影 +7 / +60 帧 = 0.12/帧 的低效长绕路（实测 −3.7）。本轮给该门加一个**每帧效率维度**吸收投影对长绕路时间成本的系统性乐观（暴雨/山雾减速未建模、未来天气隐藏→不可彻底消除）。**sim A/B 机制验证成功——v2 的双重回归（−3.7 分、+60 帧）被消除，且无 task/分段回归；但 samples 图结构上无廉价鲜度，+0.1 CI 跨 0 中性，未过"mean 正向"门槛，flag 保持关。**

### Added
- `strategy/static_planner.py` 每帧效率门：`plan_route` 改道条件由「绝对增益门」升级为「绝对增益门 **与** 每帧效率门」——`gain/extra_frames < STATIC_PLANNER_MIN_ROUTE_EFFICIENCY` 时保时间最优。`extra` = 候选与时间最优的 deliver_frame 差（总时间成本：移动+停靠+验核+冰鉴使用）。
- `_EFFICIENCY_MIN_EXTRA = 15`：效率门**仅对长绕路**（extra≥15 帧）生效——短绕路时间成本估计可信（天气暴露小），仅绝对增益门把关。精准定向 v2 根因（长绕路时间成本被低估），不误伤短绕路。
- `config.py` `STATIC_PLANNER_MIN_ROUTE_EFFICIENCY = 0.2`：阈值校准依据 = v2 乐观修正率（实际 −3.7 vs 投影 +7 / 60 帧 ≈ 0.18/帧 = 修正后盈亏平衡 ratio）。0.2 拒 0.12（v2 鲜度长绕路，修正后为负）、纳 0.26（任务 +20/77 帧长绕路，修正后仍 +6 正）。
- `tests/test_static_planner.py` `TestPlanRoute` 3 项效率门测试：`test_efficiency_gate_rejects_low_ratio_long_detour`（FAR_ICE+task ratio 0.26、阈值 0.5 → 拒）、`test_efficiency_gate_accepts_high_ratio_long_detour`（阈值 0.1 → 纳）、`test_short_detour_bypasses_efficiency_gate`（START_DATA extra=6<15、阈值 999 → 仍改道，证短绕路跳过效率门）。

### Changed
- `_best_score_for_path` 返回值 `(score, k)` → `(score, k, deliver_frame)`：透传 `project_route` 的 deliver_frame 供门控计算真实总时间成本。
- `plan_route`：`best`/`time_best` 跟踪 deliver_frame；改道门控加效率维度（`extra >= _EFFICIENCY_MIN_EXTRA and gain/extra < min_eff`）。异常安全不变（外层 try/except 回落时间最优）。
- 模块 docstring 更新为双门（绝对增益 + 每帧效率）表述。

### Tests / A/B
- 单测：268 client 全过（+3 新，零回归）。
- sim A/B 50 种子：mean 747.9 vs baseline 747.8（**+0.1，95% CI [−1.8, +1.9] 中性**）、交付帧 460.9 vs 455.4（+5.5，v2 +60 被消除）、task_base 140/140 无回归、分段（delivered/task90/mid_even/weather/opp_delivered）全一致、0 STUCK、对账 0 误差。paired 50/50/100 ties。

### Misc
- `ENABLE_STATIC_PLANNER` 保持默认关（A/B 中性非正向，未过 §1.2 门槛；CLIENT_VERSION 不 bump）。代码保留作通用 variant 平台——机制验证成功（v2 回归消除）、异常安全、0 STUCK。
- **不扫阈值逼正向**：乐观修正率 0.18/帧是物理下界——降阈值（<0.18）重新放行修正后为负的长绕路、重演 v2；升阈值更中性。samples 无正向交叉点，扫只会过拟合初赛图（违反通用原则）。
- 详见 `docs/calibration_v1.md` §8。

## [Iteration 27] - 2026-07-04 — Phase B v2 联合规划器（task+ice+route 一体求解，A/B 仍未过门槛）

针对 Iter 26 v1 评审结论（`project_route` 冻结 task_base、`plan_route` 候选集过窄、`_ice_detour_target` 分项式零和）落地真正联合求解。**sim A/B 仍未过门槛（−3.7），flag 保持关；但机制正确（多图自适应已证）、修了一个卡死 bug、根因从"分项零和"推进到"投影天气乐观（隐藏信息）"。**

### Added
- `strategy/static_planner.py` `_path_pickups(world, me, path)`：沿路径自动建模 task 领取（每任务节点领最高分任务，贪心到 task_base 130 封顶——过此零边际不浪费帧）+ ice 收集（每有库存冰源 +1 篓、+`_ICE_CLAIM_FRAMES`）。返回 (task_delta, task_frames, ice_collected, ice_frames)。让路线投影首次能权衡"绕冰源多收 ice"与"绕任务点多做 task"的零和（v1 缺的关键）。
- `project_route` 接入 `_path_pickups`：task_base += task_delta、deliver_frame 含领取/收集停靠帧、route_loss 含停靠帧鲜度损耗；返回 `ice_collected`/`task_delta`。
- `_build_candidates` + `_via_path`：`plan_route` 候选集扩展为 时间最优 + 鲜度最优 + 经冰源/任务点 waypoint 的拼接路线（含 ice+task 二段组合，覆盖共址路线）。读 `world.node_states`/`world.tasks` 动态枚举，**不写死节点**（通用）。waypoint 绕路额外帧 ≤ `_WAYPOINT_MAX_EXTRA`(80) 入选，ΔEV 门真正过滤。
- `tests/test_static_planner.py` `TestJointModel`（3 项：`_path_pickups` 计 task/ice、task 封顶、`project_route` 沿途建模）+ `TestMultiMapAdaptivity`（4 项：共址图改道、偏远图保直送、偏远+任务仍绕路、同输入两图相反决策）。`_joint_world`/`_task`/`FAR_ICE_MAP` 辅助。

### Changed
- `plan_route` 改为规划 **src→terminal 完整交付路线**（`dst` 仅签名兼容/异常回落）；`_best_score_for_path` 自算 ice 预算（库存 + 沿途可收），不再接 ice_budget 形参。
- `decision.py`：删 `_ice_detour_target`（分项式零和元凶）+ 其 `_plan` 链调用；flag-on 时 `_plan` 跳过 `_task_detour_target`（避免与 plan_route 双重决策）；`_select_path` flag-on 用 plan_route（规划到 terminal）。
- `config.py`：删 `STATIC_PLANNER_ICE_DETOUR_MAX_EXTRA`（orphan）。`STATIC_PLANNER_ICE_USE_BELOW`/`ICE_KEEP` 保留——移除分项绕路后，它们经路线耦合兑现冰鉴收集/使用（不再脱钩）。
- 模块 docstring 更新为联合规划器表述。

### Fixed
- **卡死 bug**：初版 `_via_path` 拼接的 waypoint 路径可含回溯段（如 S03→S06 最短路绕回 S01），逐帧重规划时在回环处振荡 → 7/50 局 STUCK（双方均卡至 600 帧未交付）。修法：`_via_path` 拒绝非简单路径（`len(set(full)) != len(full)`）。修复后 0 STUCK、交付率 1.000。

### Tests / A/B
- 265 client 单测全过（+7 新增；flag-off 行为零回归）。
- sim A/B 50 种子：baseline mean 747.8 / 交付 455.4；tuned（联合规划器）mean **744.1（−3.7）** / 交付 515.0（+60）/ 0 STUCK。
- 多图单测证通用自适应：冰源顺路图 → 改道；冰源偏远图 → 保直送（同输入不同图相反决策）。

### 未合入原因 / 根因推进
- v1 根因"分项式 task-ice 零和"已由联合求解消除（`project_route` 现能权衡二者），但 A/B 仍负。
- **新根因**：投影系统性低估长绕路时间成本——`path_frames` 用默认天气系数，未建模暴雨（水路 +35%）/山雾（山路 +10%）移动减速；长绕路水路段多、被低估更甚 → 投影高估长路线收益（投影 +7、实测 −3.7）。
- **未来天气对客户端隐藏**（协议）→ 投影无法准确预测 → 此乐观**不可彻底消除**。
- 不强行调参逼 samples 正向（过拟合初赛图，违反通用原则；决赛换新图）。samples 结构上不提供廉价鲜度（与 v1 同结论，现已由正确联合推理得出）。

### 决策
- `ENABLE_STATIC_PLANNER` **保持默认关**（运行期零变化，CLIENT_VERSION 不 bump）。代码保留作通用 variant 平台。
- 下一步候选：① ΔEV 门加"每帧效率"维度（gain/extra_frames ≥ 阈值）吸收不可消除的投影不确定性——拒 +7/+60=0.12/帧 的低效长绕路；② 接受 samples 中性、靠决赛新图（冰源顺路时）自然正向。详见 `docs/calibration_v1.md` §7。

## [Iteration 26] - 2026-07-04 — Phase B v1 静态规划器（仿真 A/B 未过门槛，flag 保持关）

### 触发
`docs/p0_attribution_batch2.md` §6：第二批 19 局真实 trace 确证"鲜度"为真实杠杆（输局对手
交付鲜度 90.6 vs 我 80.4 → +19 分；质量路线投影 +24 上界）。据此落地 Phase B 静态规划器作
variant，过仿真 A/B 后才合入。

### Added — `strategy/static_planner.py`（新模块，纯函数 + 异常安全）
- `freshness_optimal_path(gm, src, dst, blocked, weather_coef)`：鲜度损耗最小的路径（Dijkstra，
  边权 = 逐边 `FRESHNESS_LOSS_MOVE × frames_on_edge` + 途经处理站停靠损耗）。
- `project_route(...)`：沿给定路径交付、用 k 次冰鉴的投影终局分（复用 `core/rules.py` +
  `freshness_loss_for_path`）。冰鉴模型：每次 +10 鲜度（封顶 100）、耗 1 动作帧、可阻止 1 次
  good→bad 阈值跨越（+10≈一个阈值带）。
- `plan_route(...)`：候选路径（时间最优 / 鲜度最优）× 冰鉴用量 0..max(库存, ICE_KEEP)，取投影
  终局分最高；仅当鲜度最优高出时间最优 ≥ `STATIC_PLANNER_MIN_ROUTE_GAIN` 才改道，否则保时间
  最优。异常/不可达回落时间最优，绝不抛出。

### Changed — `decision.py`（全部 flag-gated，flag 关时 baseline 行为不变）
- `_select_path`：`ENABLE_STATIC_PLANNER` 开时用 `plan_route` 选路（frame_cost 用该路径实际帧数
  供绕行 vs 清障权衡），否则 `time_optimal_path(blocked)`（baseline）。
- `_freshness_rescue`：flag 开时阈值提至 `STATIC_PLANNER_ICE_USE_BELOW=91`（在跌破 90 阈值带前
  补鲜度，防好果转坏）。
- `_maybe_claim`：flag 开时 ice_keep 提至 `STATIC_PLANNER_ICE_KEEP=3`（支撑质量路线多次使用）。
- `_ice_detour_target`（新）：就近冰源绕路——投影"绕路收集 + 多用 1 篓冰鉴"终局分 vs 直送当前
  冰鉴用量，增益 ≥ MIN_ROUTE_GAIN 且过 `_can_afford`、额外帧 ≤ `STATIC_PLANNER_ICE_DETOUR_MAX_EXTRA`
  时选增益最高冰源。置于 `_plan` 绕路链任务绕路之后（任务优先，避免冰鉴挤占任务时间）。

### Changed — `config.py` / `scripts/sim_server.py`
- 新增 `ENABLE_STATIC_PLANNER=False`、`STATIC_PLANNER_ICE_USE_BELOW=91.0`、`STATIC_PLANNER_ICE_KEEP=3`、
  `STATIC_PLANNER_MIN_ROUTE_GAIN=0.5`、`STATIC_PLANNER_ICE_DETOUR_MAX_EXTRA=25`。
- `sim_server` 加 `--static-planner` CLI flag 翻转 config（供 variant A/B）。

### Tests
- 新增 `tests/test_static_planner.py` 16 项（freshness_optimal_path 正确性/阻塞/同点/不可达、
  project_route 匹配 rules.py 重构 + 冰鉴模型、plan_route 改道门控 + 异常回落、flag-off baseline
  不变 + flag-on 阈值/囤积提升）。总 258 client 单测全过。

### 仿真 A/B 结果（50 种子 × 2 侧 = 100 player-games/批）—— **未过 §1.2 门槛**
| 指标 | baseline | variant(任务优先+cap25) | variant(冰鉴优先,无cap) |
|---|---|---|---|
| mean 终局分 | 747.8 | 747.8（中性） | 748.3（+0.5） |
| 交付帧 mean | 455.4 | 455.4 | 480.3（+25） |
| 交付率/卡死/对账 | 1.0/0/0 | 1.0/0/0 | 1.0/0/0 |

- 冰鉴优先模式：fresh 82.66→92.56（+18 分）、goodFruit 98→100（+4）兑现，但 task 140→120（−10）、
  交付 +21 帧（−2）→ 单局净 +10、跨种子 mean 仅 +0.5（部分种子冰鉴绕路挤占任务致负）。
- 任务优先模式：冰鉴绕路被任务绕路抢占 → 不触发，逐帧与 baseline 一致（中性零回归）。

### 为何未合入（根因）
+24 上界假设 task_base 不变（150），仿真暴露被掩盖的两个成本：① 本图直送路线仅过 1 个冰源
（S06），单篓冰鉴不足以改变交付鲜度，多篓须绕路 S03/S07；② **task 与 ice 争同一 spare-time
预算（零和）**——冰鉴绕路 ~21 帧 ≈ 1 任务的时间，冰鉴优先则丢任务、任务优先则冰鉴不触发。
分项式 `_plan` 瀑布（task/ice/route 各自为政）无法同时最大化 task 与 ice。真实对手 trace 中
fresh 93 + task 165 共存，说明实战有"冰源与任务点共址"的高效路线——需全量联合 static_planner
（task bundle + ice + route 一体求解）才能兑现，是下一增量。

### Misc
- `ENABLE_STATIC_PLANNER` 保持默认关 → 运行期行为零变化，`CLIENT_VERSION` 不 bump。
- 代码保留作全量联合规划器的 variant 平台。详见 `docs/calibration_v1.md`。

## [Iteration 25] - 2026-07-04 — CLAIM_TASK 重试修复 + 鲜度投影升级（路线感知）

### 触发
`docs/p0_attribution.md` §6 重排后的两个低风险可下手点。二者均不涉阈值/开关合入，
符合 N=11<30 的"假设级"纪律（§3.7）。

### Changed — CLAIM_TASK 重试风暴修复（`client/strategy/decision.py` + `client/config.py`）
真实 trace：客户端在 S10 对已被 `OBJECT_BUSY` 拒绝的任务反复重发同 taskId（r270-296 连停
30+ 帧），11 局 13 个 waitingStuck。根因：`_apply_rejection_feedback` 只处理 PROCESS_REQUIRED
与 MOVE 拉黑，CLAIM_TASK 被拒后零处理 → 下帧 `_maybe_task` 仍见该任务 active 无 owner → 重发。
- `config.py`：新增 `REJECT_TASK_COOLDOWN_ROUNDS = 6`。
- `decision.py`：`__init__` 加 `self._task_cooldown = {}`；`_apply_rejection_feedback` 加
  CLAIM_TASK+OBJECT_BUSY 分支（设 task 级冷却）；`_maybe_task` 跳过冷却中的 taskId。
- 冷却过期自然恢复（与节点拉黑同模式），无需主动清理。

### Changed — 鲜度投影升级（`client/strategy/projection.py` + `decision.py`）
替换 `AVG_FRESHNESS_LOSS_PER_FRAME=0.06` 平摊为逐边路线感知，让投影分/gap/mode 与 ΔEV 地板
输入首次可信（后续博弈层 race/guard 与未来静态规划器的前置阻塞）。
- 新增 `freshness_loss_for_path(gm, path, weather_coef, verify_frames)`：逐边
  `FRESHNESS_LOSS_MOVE[route_type] × frames_on_edge` + 途经处理站/宫门验核停靠
  `FRESHNESS_LOSS_BASE × 帧`，乘天气鲜度系数；永不抛出。
- `_project_player`：用 `time_optimal_path` 的 path + 活跃天气系数算 `proj_fresh`，替换
  `frames_out × 0.06`。
- ΔEV 调用方改路线感知：`_detour_net_delta` 签名增 `extra_freshness_loss`；新增
  `_detour_extra_freshness_loss`（detour vs direct 逐边损耗差 + 任务处理停靠损耗）；
  `_task_detour_target`/`_task_deny_target` 传入 detour_path；bounty wait 改 `FRESHNESS_LOSS_BASE`
  停靠率（拿不到 path 时降级）。

### 为何推迟全量静态规划器
真实 trace 显示 task 双方近 180 封顶（TASK_90_REACH=1.00），"延时换 task"边际为 0；真实杠杆
更像好果保全/路线而非"交付时机"。N=11 且看不到对手分项分时，规划器优化目标不稳定，贸然替换
`_plan` 瀑布风险高、违反 §3.7。先让投影可信，待下一批 trace（含对手分项）确认杠杆后再建。

### Changed — trace 版本戳（解决"log 不记录代码版本"）
真实 trace 不记录代码版本 → 旧/新 client 行为无法区分（迭代后旧 log 失去归因价值）。
`config.CLIENT_VERSION` 由静态 "1.0" 改为 iter 标签（`"iter25"`，每轮手动 bump）+ 新增
`config.code_version()`（运行期拼 git 短 hash，平台无 git 时回落纯标签）。`main.py`/`sim_server.py`
Startup trace 改用 `code_version()`；`parser` 解析 version 入 `Report.clientVersion`，`aggregator`
`index.json` 附 `clientVersion`。支持"每轮即弃"工作流：按 clientVersion 区分 trace 所属代码版本。

### 验收
- 单测：新增 `test_task_cooldown.py`（4 项：冷却设置/跳过/过期恢复/非 OBJECT_BUSY 不触发/
  MOVE 拉黑回归）+ `test_freshness_projection.py`（7 项：逐边和/天气系数/gate 排除/MOUNTAIN≠
  平摊/空 path/投影接入）+ `test_parser.py` 补 clientVersion 断言。全量 **302 全过**
  （client 242 + sim 18 + analysis 42）。
- 仿真 50 局**零回归**：交付率 1.000、交付帧 mean 455.4、0 卡死、SimValidator 0 误差、
  对账 ok=100/mismatch=0。投影升级在镜像自博弈不改动作（gap 恒 0→mode 恒 EVEN）；
  CLAIM_TASK 冷却在 sim 不触发（sim 每玩家独立任务池不重发，CLAUDE 已注"sim 不复现客户端
  重试 bug"）——二者待真实 trace 二次验证。
- 端到端：trace Startup `version=iter25+<git短hash>` → `Report.clientVersion` → `index.json`。

### 不做（推迟）
全量 `strategy/static_planner.py`（待对手分项 trace 确认真实杠杆）；任何 `ENABLE_*` 开关/
阈值改动（N<30 纪律）；D1 GATE race（独立迭代）。

## [Iteration 24] - 2026-07-04 — Phase 0 真实 trace 归因 + 仿真器保真度校准

### 触发
用户上传 11 局真实平台对局报告（`reports/match_20260704_*.report.json`，source=platform，
playerId=2696）——这是 `iteration_plan_v2.md` Phase 0 一直在等的"地面真相"。Phase A 仿真器
此前所有结论标"待真实 trace 验证"，本批数据首次允许校准。

### Phase 0 归因（`docs/p0_attribution.md`）
- **mock@r48 坐实不可信**：真实交付帧 444–492（mean 456），mock 在 ~48，差一个数量级。
- **"冲 90"杠杆证伪**：真实 `TASK_90_REACH=1.00`、task 分 mean 179.1（近 180 封顶）——90 在真实
  环境必达，原 Phase B 主杠杆（~+220 分）不成立。Phase B 目标重定义为"交付时机 vs 质量积累"静态权衡。
- **3 局输局归因**：全为 expected_loss（无 unlucky_loss/无 bug），模式一致——我方早交付(444-448)、
  对手晚交付(475-557)却靠质量分(task/好果/鲜度)反超。真实杠杆是静态权衡未求解，非能力缺失。
- **GATE race 真实证据**：末局 r468-472 连续 5 次 `VERIFY_GATE OBJECT_BUSY`，GATE 窗口我方 ABSTAIN→
  对手抢验核。D1 GATE race 从 Phase D 提前。
- **CLAIM_TASK 重试风暴**：11 局 13 个 waitingStuck，几乎全在 S10——客户端对已 OBJECT_BUSY 任务
  反复重发同目标。未致败局但白烧用时分+鲜度，低风险清理项。
- 对账自检 ok=11/mismatch=0；投影误差 median −3（可用）；mode 实战切档 1.82/局。
- 数据缺口：`windows.oppCard` 全 null（D2 无原料）、`seed` 全 null（真实局不能 seed 配对 A/B）、
  分项分多 null（靠 rules.py 重算对账兜底）。

### Changed — 仿真器保真度校准（`scripts/sim_engine.py`）
真实 trace 暴露任务池严重失真：旧版 3 个**共享**任务 ×30=90 分（双方分、全局 completed 互斥）→
`TASK_90_REACH=0.04`，与真实 1.00 差 25 倍。按真实观察校准：
1. 任务池扩为 **10 个沿途站点任务**（S06/S08/S10/S11/S12/S13，每站 1-2 个；score 20，processRound 3），
   对齐实局"沿途站点领任务、单节点可领多个"。
2. **每玩家独立完成追踪**（`completed_by` 集合替代全局 `completed`）：双方各可累计到 task 分封顶
   停止（~140），对齐真实双玩家均 90+；`OBJECT_BUSY` 仅在本玩家重复领已完成任务时触发（复现实局
   重试风暴拒绝语义），跨玩家不互斥。
3. `_tasks_view(pid)` 按玩家视角返回 completed；`_start_claim_task`/完成结算改 per-player。

### 验收
- 50 局（100 player-games）：交付率 1.000、交付帧 452–467（mean **455.4** ≈ 真实 456）、
  `TASK_90_REACH` **1.00**（原 0.04）、0 卡死、SimValidator 对账 0 误差。
- 单测：18 sim + 42 analysis + 231 client = **291 全过**。
- 残留偏差（标"假设级"）：freshness sim 136 vs 真实 144；task_base 恒 140（真实 120-150 有方差）；
  MODE_SWITCHES 0（镜像自博弈 gap 恒 0）；waitingStuck 0（不复现客户端重试 bug）。

### 重排后续优先级（`docs/p0_attribution.md` §6）
修 CLAIM_TASK 重试风暴 → Phase B（重定义：交付时机 vs 质量）+ 鲜度投影升级 → D1 GATE race（提前）
→ Phase C 阈值校准 → D2/D3（待 oppCard trace）。继续收割真实局至 N≥30。

## [Iteration 23] - 2026-07-04 — Phase A 高保真自博弈仿真器（in-process，物理复用 rules.py）

### 触发
`docs/iteration_plan_v2.md` Iter 23 / Phase A：替换不可信的 `mock_server.py`（@r48 交付、1 帧移动、
无天气、对手静止），提供规则忠实、可复现、可 A/B 的实验台，作 Phase B 静态规划器与 Phase C 阈值校准的
证据地基。用户并行去取真实 trace（Phase 0），Phase A 不依赖平台——所有 sim 结论标"待真实 trace 验证"。

### 架构决策（与用户确认）
**进程内自博弈**（非 TCP）：新建 `scripts/sim_server.py` 直接 import 真实 `DecisionEngine`/`WorldState`/
`MatchLogger`/`rules`/`GameMap`，两侧引擎同进程跑；trace 复用 `client/main.py` 的 `_log_*` 辅助函数写出
→ 与真实客户端同格式、`analysis/parser.py` 可读。确定性同种子 A/B 天然成立（`decision.py`/`projection.py`
无 random/time，已验证）。不演练 main.py 的 socket 收发循环（与策略无关，已被 231 项 client 单测覆盖）。

### Added
- **`scripts/sim_engine.py`** — 忠实物理引擎（纯 stdlib，物理一律调 `core/rules.py`）：
  - 移动按路线距离×耗时系数（`to_station_move_amount`/`per_frame_move_amount`/`frames_on_edge`），
    advance-on-start；鲜度逐帧损耗（`freshness_loss`，移动用 `FRESHNESS_LOSS_MOVE[routeType]`，停靠用 BASE）
    + 好→坏阈值跨越（`crossed_good_to_bad_thresholds`，每跨 1 篎转坏）；天气 4 次×60 帧+提前 30 预告
    （§2.5，起始帧/类型 seed 定），暴雨命中水路/山雾命中山路按 `weather_move_multiplier`+鲜度系数；
    探路标记 45 帧可用+处理/验核 -3（§6.4.1）；宫门验核 6 帧（§252）+破关令 -3 最低 3；
    RUSH 触发四条件+450 强制（§6.5）；**路线边空动作 park WAITING+0 进度**（Iteration 8 真实败局行为）；
    设卡 `guard_defense`/攻坚 `break_guard_attack_value`/强制通行 `guard_time_tax`/风化；动作拒绝码
    （PROCESS_REQUIRED/MOVE_BLOCKED_BY_GUARD/MOVE_EDGE_NOT_FOUND/...）经 actionResults+events 回灌。
  - 动作全家桶：MOVE/PROCESS/VERIFY_GATE/CLEAR/CLAIM_RESOURCE/CLAIM_TASK/USE_RESOURCE(ICE/HORSE/INTEL)/
    SET_GUARD/BREAK_GUARD/FORCED_PASS/RUSH_PROTECT/RUSH_SPEED/SQUAD_*/DELIVER/WAIT。
- **`scripts/sim_validator.py`** — `SimValidator.validate(engine, over_data)`：用 `rules.py` 从引擎终态
  原始字段独立重算终局分，与 sim 报告的 over_data totalScore 逐项对账（两条独立代码路径），0 误差；
  不匹配抛 `SimReconcileError`。
- **`scripts/sim_server.py`** — 编排 + CLI：双 `DecisionEngine` 自博弈，复用 `main._log_frame/_log_actions/
    _log_projection/_log_engine_events/_log_over/_log_map` 写 trace 到 `logs/sim/<variant>/match_<seed>_<pid>.log`；
  matchId=`sim_<variant>_s<seed>`（聚合器按 seed 配对 A/B）；`python3 -m scripts.sim_server --games 50
  --seeds 1..50 --variant baseline`，汇总交付率/交付帧分布/mean 分/对账/卡死，退出码反映回归。
- **`scripts/tests/`** — 18 项单测：physics（移动帧数/鲜度/天气倍率/好→坏/设卡公式对齐 rules）、
  stuck（空动作 park WAITING、续行前进、WAITING 恢复）、rush（390 前不触发/450 强制/RUSH 前验核拒/RUSH 后接受）、
  validator（对账通过/篡改检出/交付场景）、endtoend（trace→parser→有效 Report）、determinism（同 seed 一致）。

### 验收（plan §5，全过）
- baseline vs baseline 50 局：**交付率 1.000（100/100）**，交付帧 428–459（mean 436.7，落在 [400,520]、非 ~r48），
  **SimValidator 对账 0 误差**，**0 WAITING 卡死**；自博弈对称（50 expected_win / 50 expected_loss）。
- `python3 -m analysis logs/sim/baseline/` 产出 `reports/`：`analysis_report.md` 分段视图齐全
  （delivered/task90_reached/task90_missed/mid_lead/mid_trail/weather_hit/opp_delivered），对账 ok=100/mismatch=0，
  `TASK_90_REACH=0.04`（已暴露 Phase B 杠杆：baseline 极少达 task-90）。
- 回归：client 231 + analysis 42 单测全过（sim 不改 client 代码，零影响）。

### 范围与待办（Phase A 不做，标"待完善/待真实 trace 验证"）
- 悬赏(bounties)/窗口争夺(contests) 留空（client `ENABLE_*` 默认关，baseline 不触发，会低估博弈分）；
  动态资源刷新不做（仅 visibleResources 一次性）；任务池 seed 合成（非平台真实任务池）；
  天气作用区域近似为按路线类型匹配（HOT 全图/暴雨水路/山雾山路）。
- 自博弈双方同配置→镜像走同路径→任务首到者得（RED 解析序先），产生系统性 RED 偏置；Phase B 静态规划器
  需非对称对手或任务错位才能充分验证 task-90 逻辑。所有 sim 结论须 Phase 0 真实 trace 校准。

## [Iteration 22] - 2026-07-04 — 日志/分析架构重构：trace 完整性 + 单局报告落盘 + 时序还原

### 触发
日志/分析架构三问：① client trace 有事实缺口（地图拓扑/对手逐帧/天气/悬赏未记，赛后归因撞墙）；
② `decisionTimeline` 只存在于 parser 内存，CLI 不落盘 → AI 读不到时序；③ timeline 被 60 条 FIFO 截断，
丢前半局根因。确立「**client trace = 传输格式（单文件·抗回传）/ repo 产物 = 分析格式（多文件·可重生成）**」
分离原则：不拆 client 日志（平台回传契约只保证 `match_*.log`），而在 repo 侧拆多文件。

### Added
- **client trace 事实补全**（`client/main.py`、`client/strategy/decision.py`，仍单文件 `match_*.log`）：
  - `Map` 事件：开局写一行拓扑快照（`nodes=[id:type|...]`、`edges=[from<->to:dist:type|...]`、`tasks=[...]`），
    用 `[a|b]` 列表格式（parser 可还原）避免值内逗号破坏字段分隔。解锁赛后路线归因（漏 task-90 可达性、绕路合理性）。
  - `Frame` 行加对手逐帧 `oppNode/oppState/oppFresh/oppGood/oppTask` + `weather`（生效天气类型）。
  - `Action` 行加决策时刻 `fresh/goodFruit/gap`（每行自解释，AI 直读不必跨 Frame/Projection join；held 好果用
    `goodFruit=`，动作消耗的好果仍用 `good=`）。
  - `Bounty` 事件：`_maybe_bounty` 触发时记 `target/reward/delta/extra/action/goodBurn`（经 `trace_events` 落盘）。
- **parser**（`analysis/parser.py`）：修 `weather_hit` 死字段（从 `Frame.weather` 置位，不再恒 False）；
  `decisionTimeline` 去 60 条 FIFO 截断（保留全量时序）；`USE_RESOURCE`(ICE/HORSE) 入 timeline；
  修 matchId 占位 `-` 恢复（Startup 行 bind 前占位→取后续真实 matchId）；捕获对手逐帧→`trajectory.opponent`
  （freshnessEnd/goodFruitEnd/nodeEnd）；`Bounty` 事件→`opponentInteraction.bounties`。
- **aggregator**（`analysis/aggregator.py`）：`build_index`（matchId→outcome/score/luckClass/segments/
  deliverFrame/taskBase/reportPath）；`build_timelines`（异常局关键事件链，按帧序渲染
  MODE/RUSH/TASK/BREAK/GUARD/WIND/REJ/ICE/HORSE/BNTY）。
- **CLI**（`analysis/__main__.py`）：产出多文件（统一落仓库根 `reports/`，与规格文档 `docs/` 解耦）——每局
  `reports/match_<id>.report.json`（含 `decisionTimeline`，落盘解决"读不到"）+ `reports/index.json`
  + `reports/analysis_report.md` + `reports/ab_report.md` + `reports/timelines.md`（有异常局才生成）。
  `--out-dir` 默认由 `docs/` 改为仓库根 `reports/`。

### Tests
- 新增 parser 7 + aggregator 3 共 +10 单测（合计 273：42 analysis + 231 client）全通过。
  覆盖 weather_hit on/off、对手轨迹、Bounty 解析、USE_RESOURCE 入 timeline、timeline 不截断(>60 全保留)、
  matchId 占位恢复、build_index 字段、build_timelines 仅异常局。
- mock 端到端 @r48 交付零回归、对账 0 误差；合成异常 trace 验证 `timelines.md` 生成。

### Misc
- `.gitignore`：分析产物从 `docs/` 解耦到仓库根 `reports/`。**内网边界**——`logs/**/*.log` gitignore
  （仅内网采集分析、不上传 GitHub）；`reports/` 入库上传（内网跑完 analysis 后 commit/push，
  外部 Claude Code pull 读分析，外部无 logs/、无需重跑）。
- 同步 CLAUDE.md（当前轮次 / §4.4 / §7 迭代日志）、architecture.md、delivery_spec.md、logs/README.md、iteration_plan_v2.md。

## [Iteration 21（续·修订）] - 2026-07-04 — 分析器基础设施落地（**分析模块移出 client，事后解析 trace**）

### 触发
承接 Iteration 21 设计评审（`docs/iteration_plan_v2.md`）的落地步骤 §11。**修订**：初版误把 `analysis/`
放进交付件 `client/`（in-client collector + report.json）。对战平台运行时无需实时分析，client 只需记录日志；
分析器属仓库侧工具，须在 client 之外、对取回的多份 trace 事后解析。故重构为：client 只记 trace →
仓库根 `analysis/` 解析+聚合。

### Added
- **`analysis/`（仓库根，client 之外，纯 stdlib）**：
  - `parser.parse_log(path) -> Report`：把 client trace `match_*.log`（`match_logger.py` 输出格式）解析为
    schemaVersion=1 结构化 `Report`。事实 100% 从日志文本抽取；行无法识别静默跳过，永不抛出。来源：
    Startup/Start→身份+seed；Frame→轨迹/验核帧/RUSH 触发/WAITING 停滞/中局 gap/天气；Action→资源·急策·任务·
    突破·设卡·窗口·决策超时；GuardDecision→设卡 defense/denial；Projection/ModeChange→投影/置信/mode 切换/
    误差；Over/Score→outcome/终局分/交付帧；Rejected/CanAffordBlock→被拒/拦截。
  - `aggregator`：跨局统计 + **场景分段**（交付/未交付、task-90 达成/未达、中局领先/落后/持平、天气/争抢、
    对手交付）+ **运气分类**（expected_win/unlucky_loss/lucky_win/expected_loss，v1 以投影误差作运气信号）+
    异常局标记 + seed 配对 A/B（95% CI + 配对胜负 + 分段回归检查 + 低样本标"假设级" N<30/100）+
    **`rules.py` 对账自检**（从 Report 原始输入重算终局分 vs trace Score 行 total，0 误差）→
    `docs/analysis_report.md`（+ 存在 variant 时的 `docs/ab_report.md`）。
  - `__main__`：CLI `python3 -m analysis <dirs>`，扫描 `match_*.log` 解析聚合；source/variant 按路径推断
    （`logs/real/`→platform、`logs/sim/`→sim；父目录 `baseline`/`tuned`→variant），可被 `--source`/`--variant` 覆盖。
- **单测**：`analysis/tests/test_parser.py`（14 项，合成 trace 逐字段断言解析）、
  `analysis/tests/test_aggregator.py`（18 项，对账/分段/异常/A/B 配对+CI+分段回归+低样本）。

### Changed（client 侧——仅日志，零分析负担）
- `client/strategy/decision.py`：`DecisionEngine` 持有 `self.trace_events`（本帧内部信号列表，main 取走落盘）；
  `_apply_rejection_feedback` 命中被拒动作时 append `("Rejected", ...)`；`_task_detour_target` 候选被
  `_can_afford`/ΔEV 拦截时 append `("CanAffordBlock", ...)`。decision 不持有 logger（保持与通信解耦）。
- `client/main.py`：`_log_engine_events` 每帧把 `engine.trace_events` 写成 trace 行；`_log_actions` 补记
  WINDOW_CARD 的 `contestType`（查 world.contests）；Start 行补 `seed`。**移除** collector 全部钩子与 report 写盘。
- `client/config.py`：**移除** `REPORT_SOURCE`/`REPORT_VARIANT`（分析专属配置不属于交付件）。
- `scripts/mock_server.py`：`build_over` 改用 `core/rules.py` 计算真实终局分（取代 stub total=0），让 trace
  Score 行携带可信分、对账 0 误差。**不影响仿真物理**。
- `.gitignore`：移除 `client/logs/*.report.json`（client 不再写）；保留忽略生成的 `docs/analysis_report.md`/`ab_report.md`。
- `logs/README.md`：改为"client 只产 trace → 复制到 logs/{real,sim}/ → `python3 -m analysis` 解析聚合"流程 + 分工边界。
- `docs/iteration_plan_v2.md`：§3.1/§3.2/§3.3/§3.6/§11 改为"分析器在 client 之外、事后解析 trace"。
- `CLAUDE.md`：§2 架构、§4.4 赛后分析、当前轮次/进度、§7 Iter 21 日志全部改为修订版。
- `docs/architecture.md`、`docs/delivery_spec.md`：模块表/数据流标注 `analysis/` 在 client 之外。

### Removed
- `client/analysis/`（整目录）、`client/tests/test_collector.py`、`scripts/analyze_logs.py`、`scripts/tests/`——
  分析代码全部移出 client / 迁入仓库根 `analysis/`。

### Verified
- `python3 -m unittest discover -s tests`（client）**231** 全通过（回归到 Iter21 前，无 collector 测试）；
  `python3 -m unittest discover -s analysis/tests -t .` **32** 全通过（14 parser + 18 aggregator，合计 **263**）。
- mock 端到端：仍 @r48 交付（fresh=97.60 / good=100 / task=60）；client/logs 仅产 `match_*.log`（**无 report.json**）；
  `python3 -m analysis logs/sim` 解析聚合后对账自检 `ok=1, mismatch=0`（0 误差）；投影分 672 == 实际 672（error=0）；
  source/variant 由路径正确推断为 sim/baseline。
- 运行期决策代码与 mock @r48 零回归。

### 待办（Iter 22+）
- Iter 22：Phase 0——打包提交收割真实对局 trace 到 `logs/real/`，`python3 -m analysis` 解析聚合，AI 读 `analysis_report.md` 做 P0 归因。
- Iter 23+：Phase A 仿真器 → Phase B 静态规划器 → Phase C 校准 → Phase D 博弈层重排（按 `iteration_plan_v2.md` §10 排期）。

## [Iteration 21] - 2026-07-04 — 迭代方式重排设计评审（分析器驱动证据型迭代，未改运行期代码）

### 触发
对项目策略做三问分析，认定三个结构性问题：① **验证真空**——20 轮 / M8 P1-P4 全建在 mock@r48 之上，仓库 `logs/` 零真实对局 trace，所有阈值/开关为未校准初值、`ENABLE_*` 全默认关、mode 在唯一测试环境恒 EVEN（博弈层对动作零影响）；② **静态层未求解**——`_plan` 是贪心瀑布而非优化，任务冲 90（解锁送达基础分 120→240 + 用时系数满 + 里程碑 35，~+220 分）只被机会式处理；③ **博弈层优先级错置**——SET_GUARD ROI 最低却占 P4，GATE 验核/deny 收益最高却最弱。范式（静态最优为体、博弈投影为用）正确但远未执行到位。

### Changed（文档，未改运行期决策代码）
- 新增 **`docs/iteration_plan_v2.md`**（完整设计与实现说明）：定新范式"**分析器驱动证据型迭代**"——证据型闭环 `假设→仿真/trace 证据→实现→A/B→仅当正向才固化`；新"done"标准须过仿真 A/B 证据。
- **分析器架构**（两层，只抽取事实不做优化——Iter 9 删旧 `analysis/` 后以正确形态回归）：in-client `client/analysis/collector.py` 运行时累计决策事件、game over 写 `report.json`(2-4KB 结构化事实，schemaVersion 化)；repo 侧 `scripts/analyze_logs.py` 跨局统计 + seed 配对 A/B + 异常局标记 + `rules.py` 对账自检 → `analysis_report.md`；Claude Code 读聚合报告归因，不直读 10w 字 trace。**代码抽取事实、AI 只做解释**。
- **Phase 路线**：Phase 0 真实 trace 收割+P0 归因 → Phase A 高保真自博弈仿真器（物理复用 `core/rules.py`，产出同格式 report）→ Phase B 静态规划器（任务-90 可达性 + 路线评分 + 鲜度投影升级，替换 `_plan` 贪心瀑布）→ Phase C 仿真驱动阈值/开关校准（产出 `calibration_v1.md`）→ Phase D 博弈层重排（D1 GATE 验核 race、D2 窗口对手出牌预测、D3 deny 按 |gap| 条件化+相对分 ΔEV；D4 SET_GUARD 冻结）。
- 同步更新 `CLAUDE.md`（当前轮次/进度、§2 架构、§3 职责、§4.4 赛后分析🟡规划中、§5 增三问认定、§6 Roadmap 增 M9、§7 增 Iteration 21 条目）、`docs/architecture.md`（数据流图增分析器漏斗、模块表增 `analysis/`、Roadmap 增 M8/M9）、`docs/delivery_spec.md`（结构化分析报告条目）。

### M8 triage（代码全部保留，处置重排）
- Layer 1 投影总线 / ΔEV 地板 / P3 ETA：**保留**（ΔEV 输入待 Phase B 鲜度模型升级后才可信）。
- P2 档位调参/悬赏/终局 race/窗口 EV、P3 任务/鲜度/资源 race：**仿真 A/B 后逐项定开/关**（Phase C）。
- P4 条件化 SET_GUARD：**冻结，不再投入**（ROI 最低，仅真实 trace 出现锁胜场景才重评）。

### Verified
- 未改运行期决策代码；`python3 -m unittest discover -s tests` 231 项全通过；mock 端到端仍 @r48 零回归。

### 待办（Iter 21+ 实现）
- Iter 21：实现分析器基础设施（`collector.py` + `report.json` schema + `analyze_logs.py` + 单测 + 对账）。
- Iter 22+：Phase 0 → A → B → C → D 按 `iteration_plan_v2.md` §10 排期推进。

## [Iteration 20] - 2026-07-03 — M8 博弈投影层 P4 §7 条件化 SET_GUARD（默认关，M8 P1-P4 全部落地）

### 触发
接入 M8 最后一项 §7：把主动设卡从二元开关（`ENABLE_OFFENSIVE`）升级为投影驱动的条件开关。SET_GUARD 本身不给我方加分，只在"锁胜局 + 对手会真的撞上卡"时用富余好果对对手施加破卡/强制通行代价——ROI 最低、默认关、设卡计划过 denial 期望价值 ΔEV 地板。

### Changed / Added（strategy/decision.py）
- `_maybe_set_guard(world, me, gm, node, terminal)` 改为分发：`ENABLE_CONDITIONAL_GUARD` → `_conditional_guard`；否则 `ENABLE_OFFENSIVE` → `_basic_set_guard`（M7 基线原样保留）。
- `_conditional_guard`（§7.1 六条件）：① mode==CONSERVATIVE 且 `gap ≥ GUARD_MIN_LEAD`(60) 锁胜；② 当前节点 type==KEY_PASS 且无有效卡；③ `eta.confidence ≥ GUARD_MIN_CONFIDENCE`(0.7)；④ 对手 `eta.eta(node) ∈ (GUARD_SETUP_FRAMES(5), GUARD_SURVIVAL_WINDOW(60)]`（设卡生效后、风化失效前通过）；⑤ `_guard_extra_fruit` 选投入 base(1)+extra 后仍守 `GUARD_KEEP_GOOD_FRUIT`(20) 的最大额外好果，无则放弃；⑥ `_can_afford(GUARD_SETUP_FRAMES)`。再过 denial 地板：`_guard_denial_value ≥ GUARD_MIN_NET_VALUE`(4)。
- `_guard_denial_value`：对手撞卡的期望分损失 = min(破卡代价, 强制通行代价)。破卡受"好/坏果各≤2 篓"(§6.3.1)约束，坏果不计交付分故优先、好果每篓≈1.8 分，受限达不到防守值则破不了；强制通行按 `rules.guard_time_tax("key_pass", defense)` 折算用时分损失。
- 设卡决策细节写 `self.guard_decision`（每帧 `_update_projection` 先清空，仅当帧真的设卡时置值）。

### Changed（config.py、main.py）
- config 增 `GUARD_MIN_LEAD=60`、`GUARD_MIN_CONFIDENCE=0.7`、`GUARD_SETUP_FRAMES=5`、`GUARD_SURVIVAL_WINDOW=60`、`GUARD_KEEP_GOOD_FRUIT=20`、`GUARD_MIN_NET_VALUE=4`；`ENABLE_CONDITIONAL_GUARD` 保持 False。
- main 每帧输出 `GuardDecision`（target/reason/gap/oppEta/extraGood/defense/denial）trace（§7.2 要求记录设卡原因/分差/目标/预计对手通过帧/投入好果）。

### Added（单测，共 +15，合计 229 全通过）
- `test_conditional_guard.py`：锁胜局设卡（extra=2）；六条件与 denial 各守卫（非 CONSERVATIVE / 领先不足 / 置信低 / ETA 窗口外 / ETA 过早 / 不在路线上 / 好果不足 / 已有卡 / 对手有坏果可低价破卡 / 对手任务分低 denial 不足）；分发（两开关都关不设卡、`ENABLE_OFFENSIVE` 基线保留、条件化优先于基线）。

### Verified
- `py -m unittest discover -s tests`：229 项全通过。
- mock 端到端（127.0.0.1:8100）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100/task 60）；`GuardDecision` 计数 0——所有 race/guard 开关默认关，**零回归**。

### 里程碑：M8 博弈投影层 P1-P4 全部落地
- P1 投影总线 + P1.5 ΔEV 分数质量地板（启用，纯观测+守卫）；P2 §5 低风险增量（启用：档位调参/悬赏/终局 race/窗口 EV/突破烧好果）；P3 §6 中风险 race（默认关：ETA/任务/鲜度·资源）；P4 §7 条件化 SET_GUARD（默认关）。所有增量动作过 `_can_afford` + ΔEV/denial 地板，信息不足默认 EVEN=既有基线；mock 全程零回归 @r48。

### 待办（P0，进入真实对局迭代）
- 拿真实对局 trace 归因，用 `Projection`/`Eta`/`ModeChange`/`GuardDecision` trace 校准全部阈值（`LEAD_SAFE`/confidence 公式/投影与 ETA 精度/`ENDGAME_RACE_WINDOW`/窗口 EV 好果下限/突破时间税/任务·资源 race 阈值/`GUARD_*`）。
- 逐项打开 P3/P4 开关（`ENABLE_TASK_RACE`/`ENABLE_TASK_DENY`/`ENABLE_FRESHNESS_RACE`/`ENABLE_RESOURCE_DENY`/`ENABLE_CONDITIONAL_GUARD`），用真实 trace 验证 ΔEV/胜负收益为正后固化。


## [Iteration 19] - 2026-07-03 — M8 博弈投影层 P3 §6.3 鲜度/资源 race（默认关）

### 触发
接入 P3 race 层最后一项 §6.3：鲜度阈值触发好果转坏，故双方接近阈值时"路线/冰鉴时机"有博弈价值。两子能力逐项带开关、默认关，真实 trace 验证后再开。至此 P3 race 层（§6.1/§6.2/§6.3）全部就绪，仅剩 Layer 4 §7。

### Added / Changed（strategy/decision.py）
- **鲜度 race**：`_freshness_rescue(world, me)`（签名加 `world`）+ `_losing_freshness_race(world, me)`。开启 `ENABLE_FRESHNESS_RACE` 且对手鲜度 − 我方鲜度 ≥ `FRESHNESS_RACE_GAP`(10)（我方处劣势）时，把冰鉴使用阈值从 `ICE_BOX_USE_BELOW`(78) 抬到 `ICE_BOX_RACE_USE_BELOW`(88)，提前用冰鉴保阈值——符合守卫"冰鉴以保阈值为核心、不为省资源致好果转坏"（提前用只会更保护）。默认关时行为与现状完全一致。
- **资源 race**：`_maybe_resource_race(world, me, gm, node, terminal)`（`ENABLE_RESOURCE_DENY`）。用 §6.1 `opponent_eta.eta(nodeId)` 找对手正争夺（ETA 有限）、我方到该点帧数 ≤ 对手 ETA + `RESOURCE_DENY_ETA_MARGIN`（抢得到、不跑空趟）、有冰鉴库存、额外帧 ≤ `RESOURCE_RACE_MAX_EXTRA_FRAMES`(20,不显著偏离)、过 `_can_afford`、且我方冰鉴未囤够 `RESOURCE_RACE_ICEBOX_KEEP`(2) 的路线附近节点，选对手最快到达（最紧迫）者作绕路目标；到点由 `_maybe_claim` 领取（开关开时其冰鉴保有量抬到 race 值）。
- `_plan` race 绕路顺序：任务 deny（§6.2）→ 资源(冰鉴)争夺（§6.3）→ 任务追平/机会式绕路。

### Changed（config.py）
- 新增 `ENABLE_FRESHNESS_RACE=False`、`FRESHNESS_RACE_GAP=10.0`、`ICE_BOX_RACE_USE_BELOW=88.0`、`RESOURCE_RACE_MAX_EXTRA_FRAMES=20`、`RESOURCE_RACE_ICEBOX_KEEP=2`、`RESOURCE_DENY_ETA_MARGIN=0`；`ENABLE_RESOURCE_DENY` 保持 False。

### Added（单测，共 +12，合计 214 全通过）
- `test_freshness_resource_race.py`：鲜度 race（劣势提前用冰鉴、鲜度相近不提前、常态阈值内仍用、无冰鉴不动作、开关关闭）；资源 race（抢占对手争夺冰鉴、对手不可达不抢、抢不过不跑空趟、已足额不绕路、开关关闭）；默认关校验。

### Verified
- `py -m unittest discover -s tests`：214 项全通过。
- mock 端到端（127.0.0.1:8099）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100/task 60）——四个 race 开关（TASK_RACE/TASK_DENY/FRESHNESS_RACE/RESOURCE_DENY）默认关，`_freshness_rescue` 阈值不变、`_maybe_resource_race` 返回 None，**零回归**。

### 里程碑：P3 race 层全部接入（默认关）
- §6.1 对手轨迹 ETA（纯观测）、§6.2 任务 race（追平/Deny）、§6.3 鲜度/资源 race 均已实现并单测覆盖，全部默认关。所有 race 依赖 ETA（对手意图不可观测，轨迹变化打折 confidence），须真实 trace 校准后逐项打开。仅剩 Layer 4 §7 条件化 SET_GUARD。

### 待办
- P0：真实 trace 校准 `LEAD_SAFE`/confidence/`ENDGAME_RACE_WINDOW`/窗口 EV 好果下限/ETA 精度/任务·资源 race 阈值，并逐项打开 P3 开关验证 ΔEV/胜负收益为正。
- P4：§7 条件化 SET_GUARD（`ENABLE_CONDITIONAL_GUARD` 默认关，把 denial 对胜负的期望价值计入 ΔEV 地板）。


## [Iteration 18] - 2026-07-03 — M8 博弈投影层 P3 §6.2 任务 race（追平 + Deny，默认关）

### 触发
在 §6.1 ETA 之上接入 §6.2：任务分 race 有两面——落后时补差（任务分<90 边际价值高，因 time_score×min(task,90)/90）、以及抢占对手正奔赴的关键任务点阻其里程碑。按 P3 规范逐项带开关、默认关，真实 trace 验证 ΔEV 为正后再开。

### Added / Changed（strategy/decision.py）
- **追平**：`_task_catch_up_active(world, me)`（`ENABLE_TASK_RACE`，对手任务分 ≥ `TASK_RACE_OPP_THRESHOLD`(80) 且我方 < 90）。触发时 `_task_detour_target` 把 `seek_target` 抬到 ≥90、`detour_max` 抬到 `AGGRESSIVE_TASK_DETOUR_MAX_EXTRA_FRAMES`——仍逐候选过 `_can_afford` 与档位 ΔEV 地板（不放松分数守卫）。
- **Deny**：`_task_deny_target(world, me, gm, node, terminal)`（`ENABLE_TASK_DENY`）。遍历可领取任务（非对手保护/占用/SKIP），用 §6.1 `opponent_eta.eta(nodeId)` 判对手可达且正奔赴、我方到该点帧数 ≤ 对手 ETA + `TASK_DENY_ETA_MARGIN`（不跑空趟）、`_crosses_milestone`(60/90/110) 判抢占能阻断对手里程碑；过 `_can_afford` 且 `_detour_net_delta ≥ 0`（不自伤，denial 是额外收益）；选对手 ETA 最早（最紧迫）者。
- `_crosses_milestone(base, gain)`：base+gain 是否跨过 60/90/110。
- `_plan`：任务段改为先 `_task_deny_target`（默认关），否则 `_task_detour_target`（含追平），再回退终点。

### Changed（config.py）
- 新增 `ENABLE_TASK_RACE=False`、`TASK_RACE_OPP_THRESHOLD=80`、`TASK_DENY_ETA_MARGIN=0`；`ENABLE_TASK_DENY` 保持 False。

### Added（单测，共 +14，合计 202 全通过）
- `test_task_race.py`：追平（覆盖 CONSERVATIVE 被追平放宽、对手未逼近不追、自身已达 90 不追、`_task_catch_up_active` 谓词、开关关闭）；Deny（抢占跨里程碑任务、对手不可达不抢、无里程碑不抢、抢不过不跑空趟、被对手保护不抢、开关关闭、`_crosses_milestone`）；默认关校验。

### Verified
- `py -m unittest discover -s tests`：202 项全通过。
- mock 端到端（127.0.0.1:8098）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100/task 60）——两开关默认关，`_task_detour_target` 无追平加成、`_task_deny_target` 直接返回 None，**零回归**。

### 设计说明
- 两子能力默认关（P3 规范）：真实 trace 验证 ΔEV/胜负收益为正后再开；deny 的价值主要在"对手失去里程碑"，`_detour_net_delta≥0` 仅保证我方不自伤（我方 claim 该任务本身也得分）。
- deny 依赖 ETA（对手意图不可观测，用最短路 ETA 作代理），故与 §6.1 一样受"轨迹变化打折 confidence"的前提约束，务必真实 trace 校准后再启用。

### 待办
- P0：真实 trace 校准 `LEAD_SAFE`/confidence/`ENDGAME_RACE_WINDOW`/窗口 EV 好果下限/ETA 精度/**任务 race 阈值与 deny 命中率**。
- P3 续：§6.3 鲜度/资源 race（`ENABLE_RESOURCE_DENY` 默认关）；P4 条件化 SET_GUARD。


## [Iteration 17] - 2026-07-03 — M8 博弈投影层 P3 §6.1 对手轨迹 ETA（纯观测）

### 触发
进入 P3。§6.1 是 race 层的观测基础设施：估算对手到宫门/终点/关键节点的帧数，作为后续 §6.2 任务 race、§6.3 鲜度/资源 race 的 tie-breaker/争夺判断输入。像 P1 投影总线一样**纯观测、不改任何动作**；动作层（§6.2/§6.3）仍在默认关开关后。

### Added（strategy/projection.py）
- `OpponentEta` 数据类：`from_node / to_gate / to_finish / to_nodes / verified / confidence`，含 `eta(node)` 查询。
- `Projector.build_opponent_eta(world)`：以对手 `current_node_id`/`next_node_id`/`move_progress`/`verified` + 地图边权/宫门验核耗时估算 ETA。
  - `_eta_base`：在途（0<progress<1）以 `next_node` 起算并加"到 next 的残余帧"（`ceil(edge_frames*(1-progress))`，§4.3 保守口径）；否则以 current 起算。
  - `to_finish` 未验核时加 `_verify_frames`。
  - `_eta_targets`：活跃任务节点 + 有库存资源节点。
  - `_eta_confidence`：随终局上升，按 `_track_opp_route`（对手原地改目标=路线变更）的变更计数打折（意图不可观测，§4.4）。
- `Projector` 增跨帧状态 `_opp_prev`/`_opp_route_changes`。

### Changed（strategy/decision.py、main.py）
- `DecisionEngine._update_projection` 每帧构建并存 `self.opponent_eta`（异常安全、**不改任何动作**）。
- `main.py` 每帧输出 `Eta matchId=.., round=.., oppFrom=.., toGate=.., toFinish=.., verified=.., conf=..` trace（供校准 ETA 精度）。

### Added（单测，共 +8，合计 188 全通过）
- `test_opponent_eta.py`：在节点/在途（move_progress）ETA、未验核加验核帧、任务/资源节点 ETA、无对手降级、置信随回合上升、轨迹变化（原地改目标）降低置信、接入 `decide` 不改动作。

### Verified
- `py -m unittest discover -s tests`：188 项全通过。
- mock 端到端（127.0.0.1:8097）：仍 @r48 `DELIVER_SUCCESS`；`Eta` trace 每帧输出（mock 对手静止 S01 → toGate=396/toFinish=416 恒定、conf 0.30→0.34），**零回归**。

### 设计说明
- ETA 假设对手沿最短路前进（对手意图不可观测）；轨迹频繁变化时按变更计数打折 confidence。只作只读输入，不直接产生动作。
- 未计入天气对边耗时的影响（与本方 `time_optimal_path` 口径一致，均忽略天气）；待 P0 真实 trace 校准 ETA 精度后再决定是否精细化。

### 待办
- P0：真实 trace 校准 `LEAD_SAFE`/confidence/`ENDGAME_RACE_WINDOW`/窗口 EV 好果下限/**ETA 精度（对比 Eta trace 与对手真实到达帧）**。
- P3 动作层：在 ETA 之上接入 §6.2 任务 race、§6.3 鲜度/资源 race（`ENABLE_TASK_DENY`/`ENABLE_RESOURCE_DENY` 默认关，逐项过 `_can_afford`+ΔEV 地板、真实 trace 验证为正后打开）；P4 条件化 SET_GUARD。


## [Iteration 16] - 2026-07-03 — M8 博弈投影层 P2 突破烧好果意愿（§5.1 行3）接入决策（P2 全部完成）

### 触发
接入 P2 最后一项 §5.1 行3：突破（清障/破卡）时是否烧好果按档位取舍。触碰交付关键的 `_breakthrough` 路径，故严格保持"必要突破照常发生、绝不因保好果而误交付"。

### Changed（strategy/decision.py）
- `_breakthrough` 增 CONSERVATIVE 保好果分支：障碍（T04 优先后）与敌卡在 `_prefer_forced_pass` 为真时改出 `FORCED_PASS`（不烧好果）；否则维持既有 `CLEAR` / `BREAK_GUARD`。
- 新增 `_prefer_forced_pass(world, me, gm, nxt, terminal)`：仅当 `tuning.protect_good_fruit_on_breakthrough`（=CONSERVATIVE）且 `_forced_pass_tax` 过 `_can_afford`（强制通行时间税仍能按时交付）时返 True。负担不起时间税 → 回退烧好果攻坚，保交付下限。
- 新增 `_forced_pass_tax`：纯障碍用固定 `rules.OBSTACLE_TIME_TAX`；敌卡按节点类型（obstacle_node/key_pass/gate/normal）+ 防守值走 `rules.guard_time_tax`（§6.3.2）。
- 引入 `from core import rules`。
- **必要突破前提下此改动只改"方法"（烧果 vs 付时间），不改"是否突破"**；EVEN/AGGRESSIVE 行为不变（维持烧好果攻坚更快通过）。

### Changed（strategy/tuning.py）
- `StrategyTuning` 增 `protect_good_fruit_on_breakthrough`：CONSERVATIVE=True（领先锁好果），EVEN/AGGRESSIVE=False。

### Added（单测，共 +10，合计 180 全通过）
- `test_breakthrough_fruit.py`：CONSERVATIVE 障碍/敌卡突破出 FORCED_PASS、EVEN/AGGRESSIVE 出 CLEAR/BREAK_GUARD、时间紧（逼近 600 帧）CONSERVATIVE 回退 CLEAR 保交付、`protect_good_fruit_on_breakthrough` 档位映射、`_forced_pass_tax` 障碍固定税/敌卡防守值缩放。

### Verified
- `py -m unittest discover -s tests`：180 项全通过。
- mock 端到端（127.0.0.1:8096）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100/task 60），障碍 S13 仍走 SQUAD_CLEAR/CLEAR——mock mode 恒 EVEN，行为不变，**零回归**。

### 里程碑：P2 低风险增量全部完成
- §5.1 行1/2（档位任务目标/绕路上限 + §3.3 ΔEV 地板）、行3（突破烧好果意愿）、行4（护果令时机）、行5（窗口出牌）；§5.2 悬赏机会主义；§5.3 终局交付 race；§5.4 窗口 EV——均已接入 `decision.py`，各受 `_can_afford` 与（相关处）ΔEV 地板守卫，信息不足默认 EVEN=既有基线（mock 全程零回归 @r48 交付）。

### 待办
- P0：真实对局 trace 归因 + 校准 `LEAD_SAFE`/confidence/投影精度/`ENDGAME_RACE_WINDOW`/窗口 EV 好果下限/突破时间税估算（当前 mode 前中段恒 EVEN，P2 差异主要在中后段切档时显现）。
- P3-P4：中风险 race（ETA/任务·资源，逐项开关）、条件化 SET_GUARD（默认关），真实 trace 验证 ΔEV 为正后逐项打开。


## [Iteration 15] - 2026-07-03 — M8 博弈投影层 P2 窗口 EV（§5.4 + §5.1 行5）接入决策

### 触发
P2 §5.1-§5.3 已就绪。接入 §5.4：把 `_window_card` 从"出第一张可出的牌"升级为**代价感知 + 档位门控**的期望收益选择，锁住交付好果不被窗口无谓消耗。至此 P2 低风险增量基本完成（仅剩 §5.1 行3）。

### Changed（strategy/decision.py）
- 重构 `_window_card(world, me)`，依任务书 §5.4.3 成本口径分两类：
  - **无代价牌**（不减交付好果分、不拖交付时间）：兵争(1 行动点，仅用于窗口)、验牒(1 文书；`PASS_TOKEN`/`OFFICIAL_PERMIT` 无其它主动用途)、免费强行(已有马/疾行 buff 生效时免消耗)。按克制强度 **兵争 > 验牒 > 免费强行** 恒出——出无代价有效牌弱优于弃权（可能赢本拍，输了不损耗）。
  - **有代价牌**：献贡(消耗 1 好果 = 直接减交付好果分，唯一有交付代价的牌)。仅**非 CONSERVATIVE** 且窗口价值明显 + 好果 > 档位下限 + 鲜度 ≥ 80 时出。消耗马的强行**不再出**（马用于交付提速，价值高于一次窗口）。
- 新增 `_window_worth_cost(contest)`：按 `contestType` 判窗口是否值得烧好果（TASK/GATE/PASS/DOCK）。

### Changed（config.py）
- 新增 `WINDOW_XIANGONG_MIN_GOOD_EVEN=50`、`WINDOW_XIANGONG_MIN_GOOD_AGGRESSIVE=12`、`WINDOW_VALUABLE_CONTEST_TYPES=(TASK,GATE,PASS,DOCK)`。

### Added（单测，共 +14，合计 170 全通过）
- `test_window_ev.py`：无代价牌优先级(兵争>验牒>免费强行)、CONSERVATIVE 不烧好果、EVEN/AGGRESSIVE 好果下限差异、低价值窗口(RESOURCE)不烧、鲜度<80 不可献贡、只有马不烧马、无窗口返回 None。

### Verified
- `py -m unittest discover -s tests`：170 项全通过。
- mock 端到端（127.0.0.1:8095）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100/task 60）——mock 不创建窗口，`_window_card` 返回 None，**零回归**。

### 设计说明 / 暂缓
- 未接入"对手历史窗口出牌倾向"预测（§5.4 输入之一）：需可靠的跨帧对手出牌历史与真实 trace，暂缓；当前用"无代价牌恒出 + 有代价牌按价值/档位门控"的稳健 EV 近似。
- **P2 低风险增量至此基本完成**：§5.1 行1/2/4/5、§5.2、§5.3、§5.4 均已接入；仅剩 §5.1 行3（突破烧好果意愿，触交付关键 `_breakthrough` 路径，待真实 trace）。

### 待办
- P0：真实 trace 归因 + 校准 `LEAD_SAFE`/confidence/投影精度/`ENDGAME_RACE_WINDOW`/窗口 EV 好果下限。
- 评估进入 P3（中风险 race：ETA/任务/资源，逐项开关，默认关）。


## [Iteration 14] - 2026-07-03 — M8 博弈投影层 P2 终局交付 race（§5.3）接入决策

### 触发
P2 §5.1/§5.2 已就绪。继续接入 §5.3：现有急策只看我方状态；用对手投影把终局的 `RUSH_SPEED`/`RUSH_PROTECT` 取舍升级为"对手将交付时，落后抢交付帧 / 领先锁交付质量"，且不破坏已验证交付条件。

### Added / Changed（strategy/decision.py）
- 新增 `_endgame_race_state(world, me)`：RUSH 相位下，对手投影 `deliver_frame` 与我方 `deliver_frame` 均在 `ENDGAME_RACE_WINDOW`(20) 帧内 → `racing=True`；`gap≤0`（落后/接近）→ `behind=True`。缺投影/未到 RUSH/信息不足 → `(False, False)`。终局对手路线收敛、投影 confidence 天然偏高，据此决策可信。
- `_rush_speed_warranted` 改为 race-aware：先保留"未用急策/鲜度安全/不叠加马"三道硬约束；再按 race：
  - race 且落后/接近 → 放宽"远离终点"门槛，只要仍有移动余量即 `RUSH_SPEED` 抢交付帧；
  - race 且领先 → 抑制疾行（不烧 +25% 鲜度损耗，把急策留给护果锁质量）；
  - 非 race → 维持原有"路线距离 > `HORSE_MIN_REMAINING_DISTANCE` 才疾行"的保守门槛。
- 领先且鲜度临界 → `RUSH_PROTECT` 仍由既有 `_maybe_rush_protect`（RUSH 相位 + 鲜度 < 档位阈值）覆盖，无需重复。

### Added（单测，共 +11，合计 156 全通过）
- `test_endgame_race.py`：落后+近终点抢帧（原本近处不疾行）、非 race 近处不冲、领先抑制疾行（原本远处会疾行）、非 race 远处保持原疾行、鲜度危急不冲、持马不冲；`_endgame_race_state` 的 race/behind/领先/对手远/非 RUSH/无对手投影各分支。

### Verified
- `py -m unittest discover -s tests`：156 项全通过。
- mock 端到端（127.0.0.1:8094）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100/task 60）——mock 对手不推进、不下发悬赏，race 分支不改变既有单人最优路径，**零回归**。

### 待办（后续迭代）
- P0：真实 trace 归因 + 校准 `LEAD_SAFE`/confidence/投影精度/`ENDGAME_RACE_WINDOW`。
- P2 续：窗口 EV（§5.4）；§5.1 行3/5 仍缓（触交付关键路径）。P3-P4：ETA/任务·资源 race/条件化 SET_GUARD（开关默认关）。


## [Iteration 13] - 2026-07-03 — M8 博弈投影层 P2 悬赏机会主义（§5.2）接入决策

### 触发
P2 档位调参已就绪，继续接入 §5.2：把已解析但未使用的 `world.bounties` 变成"顺路低代价正 EV 收益"——破对手设卡拿破关悬赏，且严格受时间地板与 §3.3 分数地板保护，不动摇 delivery-first。

### Added（strategy/decision.py）
- `_maybe_bounty(world, me, gm, node, terminal)`：接入 `_plan`（opportunistic 之后、set_guard 之前）。
  - 候选：`world.bounties` 中 `active && !completed && !winner`，节点存在**对手有效设卡**（`active_guard_owner()` 非本方），且 `_plan_attack` 能低成本破（防守值可达、破卡后好果不跌破 `KEEP_GOOD_FRUIT_MIN`）。
  - 路由：以阻塞感知的到终点帧数为基线 `direct`；把目标悬赏卡从阻塞集移除后求 `node→BG` 与 `BG→终点`，额外帧 `extra=(c1+c2)-direct`（顺路可为负）；要求 `extra ≤ BOUNTY_MAX_EXTRA_FRAMES`(25)。
  - 双地板与门：`_can_afford`（时间）+ `net_score_delta ≥ BOUNTY_MIN_NET_SCORE`(15)——悬赏原始分作 `extra_bounty`（`bounty_score` 含交付 +20 奖励）、破卡好果作 `good_fruit_burned`、额外耗时与鲜度损耗计入代价。
  - 动作：与悬赏卡相邻（路径长 2）→ `BREAK_GUARD(BG, 最小好/坏果, rushTactic?)`；否则沿"绕开其它阻塞、允许进入目标卡"的路径 `MOVE` 靠近一步，逐帧复评直至相邻破卡。
  - 守卫：`CONSERVATIVE`（锁胜，不为悬赏花好果/时间）与 `RUSH`（保交付优先）直接不追。

### Added（单测，共 +10，合计 145 全通过）
- `test_bounty_opportunism.py`：相邻破卡输出 `BREAK_GUARD`、端到端管线也决策破卡、近路靠近输出 `MOVE`、跳过高防守(不可低成本破)/自方设卡/超绕路上限/零收益(ΔEV<15 被地板拒)/已完成、`CONSERVATIVE` 与 `RUSH` 不追。

### Verified
- `py -m unittest discover -s tests`：145 项全通过。
- mock 端到端（127.0.0.1:8093）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100/task 60）——mock 不下发 `bounties`/`guard`，`_maybe_bounty` 不触发，**零回归**。

### 设计说明
- 破关悬赏因 `bounty_score` 有 +20 交付奖励，几乎总是正 EV；故实际约束主要是"低成本可破 + 顺路(≤25 帧)"两道，`BOUNTY_MIN_NET_SCORE` 主要挡零/负收益的无谓破卡。
- mock 未建模 guard/bounty/BREAK_GUARD 结算（`bounties` 恒空），§5.2 以单测为验收；真实平台数据到位后再复核 ΔEV 与破卡收益。

### 待办（后续迭代）
- P0：真实 trace 归因 + 校准 `LEAD_SAFE`/confidence/投影精度（mode 前中段恒 EVEN，P2 差异只在中后段切档时显现）。
- P2 续：终局交付 race（§5.3）、窗口 EV（§5.4）；P3-P4：ETA/任务·资源 race/条件化 SET_GUARD（开关已登记默认关）。


## [Iteration 12] - 2026-07-03 — M8 博弈投影层 P2 档位调参接入决策（§5.1 行1/2/4 + §3.3 ΔEV 地板）

### 触发
P1/P1.5 已就绪（投影总线 + `net_score_delta`）。本轮把 §5.1 中**可清晰参数化、且不威胁交付下限**的档位调参正式接入决策：任务绕路目标/上限（行1/2）与护果令时机（行4），并给绕路这一增量动作套上 §3.3 分数质量地板——这是防 AGGRESSIVE 放宽绕路上限后重演 839cfc9「过度贪任务/烧好果」败局的核心闸门。

### Changed（strategy/decision.py）
- `DecisionEngine` 每帧 `_update_projection` 内 `self.tuning = tuning_for_mode(mode)`（异常/缺投影回落 EVEN=既有默认）。
- `_task_detour_target`：改用 `tuning.task_seek_target` / `tuning.task_detour_max_extra_frames`；对每个候选新增与门第二道守卫——`net_score_delta ≥ tuning.action_min_net_score`（时间地板 `_can_afford` 之外的分数地板）。任务分增量取 `inquire.tasks[].score`。
- 新增 `_detour_net_delta(me, task_pts, extra_frames)`：以本方投影 `my_projection`（deliver_frame/task/good/fresh）为基线，计入额外耗时（推迟交付→用时分）与额外鲜度损耗（`extra_frames × AVG_FRESHNESS_LOSS_PER_FRAME`，含跨阈值转坏）；缺投影或直达都交付不了则返回 -inf（拒绝绕路）。
- `_maybe_rush_protect` / `_rush_speed_warranted`：护果令触发阈值由写死 `config.RUSH_PROTECT_FRESHNESS_BELOW` 改为 `tuning.rush_protect_freshness_below`。

### Changed（strategy/tuning.py、config.py）
- `StrategyTuning` 新增字段 `rush_protect_freshness_below`；`tuning_for_mode` 映射：CONSERVATIVE/EVEN=`RUSH_PROTECT_FRESHNESS_BELOW`(90)、AGGRESSIVE=`AGGRESSIVE_RUSH_PROTECT_FRESHNESS_BELOW`(75，落后时更克制、把急策留给冲刺)。
- `config.py` 新增 `AGGRESSIVE_RUSH_PROTECT_FRESHNESS_BELOW = 75.0`。

### Added（单测，共 +9，合计 135 全通过）
- `test_mode_tuning_wiring.py`：EVEN 取近处高价值任务、CONSERVATIVE(target=0) 禁绕路、AGGRESSIVE 放宽上限取 EVEN 上限外的绕路、ΔEV 地板拒低价值绕路且 AGGRESSIVE 也不放净负分、护果令阈值三档时机（EVEN@85 用/AGGRESSIVE@85 不用/AGGRESSIVE@70 用）。
- `test_game_theory_tuning.py`：新增护果令阈值按档位断言。

### Verified
- `py -m unittest discover -s tests`：135 项全通过。
- mock 端到端（127.0.0.1:8092）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100/task 60）——mode 恒 EVEN（confidence<0.55），tuning=既有默认，ΔEV 地板不误伤有益的顺路/低成本绕路，**零回归**。

### 设计取舍（本轮刻意不做）
- §5.1 行3（突破烧好果意愿）触碰交付关键的 `_breakthrough` 路径、行5（窗口出牌）涉及窗口牌代价语义，二者错判可能损失交付；§5.2 悬赏/§5.3 终局 race/§5.4 窗口 EV 为新增机会动作。均留待真实 trace 验证与逐项开关，避免在无真实数据时动摇 delivery-first 下限。

### 待办（后续迭代）
- P0：真实 trace 归因 + 校准 `LEAD_SAFE`/confidence/投影精度（当前 mode 前中段恒 EVEN，P2 差异只在中后段切档时显现）。
- P2 续：悬赏机会主义（§5.2）、终局交付 race（§5.3）、窗口 EV（§5.4）；P3-P4：ETA/任务·资源 race/条件化 SET_GUARD（开关已登记默认关）。


## [Iteration 11] - 2026-07-03 — M8 博弈投影层 P1+P1.5 落地（纯观测，不改动作）

### 触发
按 `docs/game_theory_projection_strategy.md` 的落地顺序实现零风险先行的 P1（投影总线）与 P1.5（分数质量地板）：把 `world.opponent` 升级为策略一等**观测**输入，为后续 Layer 2-4 的档位调参与博弈动作提供基础设施与校准依据。P0（真实 trace 归因）与 P2-P4（改动作层）待真实对局日志。

### Added（strategy/projection.py，新模块）
- `Projector.build(world)`：每帧投影双方终局分/交付帧，计算 gap 与风险档位，产出只读 `ProjectionBus`；异常安全（任何缺信息都降级为 EVEN、绝不抛出）。
- `project_final_score(...)`：复用 `core/rules.py` 纯函数把投影字段组合成投影终局分（交付/未交付两套口径，§4.2）。
- `net_score_delta(...)`（§3.3，P1.5）：纯函数估算某增量动作对投影终局分的净影响 ΔEV，计入任务/悬赏增量与耗时/烧好果/鲜度损耗（含跨阈值转坏）代价；供 P2+ 增量动作与 `_can_afford` 组成"时间地板 ∧ 分数地板"与门。
- `ModeMachine`：gap→mode 状态机，带滞后（连续 `MODE_HYSTERESIS_FRAMES` 帧同向才切档）与低置信回落 EVEN。
- `RiskMode`/`Projection`/`ProjectionBus` 数据结构（§4.1）。

### Added（strategy/tuning.py，新模块）
- `StrategyTuning` + `tuning_for_mode(mode)`（Layer 2 §5.1）：mode→{task_seek_target/task_detour_max_extra_frames/action_min_net_score}；EVEN **严格等于** config 既有默认；三档 ΔEV 阈值均非负（铁律：更进取只放宽下限，不许净负分）。**当前尚未被决策消费**（保证 P1 端到端不变），P2 起接入。

### Changed（decision.py、main.py、config.py）
- `DecisionEngine` 持有 `Projector`，`decide()` 每帧 `_update_projection(world)` 构建投影总线并记录切档事件——**纯观测，不改变任何动作输出**。
- `main.py` 每帧输出 `Projection matchId=.., round=.., myScore=.., oppScore=.., gap=.., mode=.., myDeliver=.., oppDeliver=.., confidence=..`；切档另输出 `ModeChange from=.. to=.. reason=..`（§8）。
- `config.py` 新增 §9 常量：`LEAD_SAFE=40`/`MODE_HYSTERESIS_FRAMES=5`/`PROJECTION_MIN_CONFIDENCE=0.55`/`ACTION_MIN_NET_SCORE*`（三档）/`AGGRESSIVE_TASK_*`（绕路上限 90）/`CONSERVATIVE_TASK_*`/悬赏与终局阈值/`ENABLE_TASK_DENY`·`ENABLE_RESOURCE_DENY`·`ENABLE_CONDITIONAL_GUARD`（默认关）。

### Added（单测，共 +30，合计 126 全通过）
- `test_projection.py`（投影分/交付帧、对手缺失→低置信 EVEN、验核加帧、置信随回合上升、观测不改动作）、`test_risk_mode.py`（阈值+滞后+低置信回落）、`test_net_score_delta.py`（正/负 ΔEV、烧好果败局模式、跨鲜度阈值）、`test_game_theory_tuning.py`（三档映射、EVEN=默认、阈值非负）。

### Verified
- `py -m unittest discover -s tests`：126 项全通过。
- mock 端到端（127.0.0.1:8091）：仍 @r48 `DELIVER_SUCCESS`（fresh 97.6/good 100），动作与现状逐帧一致——P1 零风险约束达成；`Projection` trace 每帧输出，前段 confidence 0.30–0.34（<0.55）故 mode 恒 `EVEN`、无 `ModeChange`（符合"前中段停 EVEN、切换主战场在中后段"的设计预期）。

### 待办（后续迭代）
- P0：拿真实对局 trace 做败局归因，校准 `LEAD_SAFE`/confidence 公式/投影精度（当前用 `AVG_FRESHNESS_LOSS_PER_FRAME=0.06` 粗估、悬赏两侧置 0）。
- P2-P4：逐项接入档位调参/悬赏/终局 race/窗口 EV/任务·资源 race/条件化 SET_GUARD，每项过 `_can_afford`+ΔEV 地板、默认关、真实 trace 验证为正后打开。


## [Iteration 10] - 2026-07-03 — 博弈投影层设计评审与优化（仅文档，未改运行期代码）

### 触发
对 `docs/game_theory_projection_strategy.md`（对手投影驱动策略）做基于代码/协议的合理性评审并据此优化设计；同步规格文档。

### Changed（docs/game_theory_projection_strategy.md）
- **修正时序前提（§1.1）**：mock 仿真 ~r48–r55 交付是简化模型产物，不代表实战；真实平台交付在 **450+**，故存在约 450 帧争夺中局——据此上调 Layer 3/4 的价值评估（从"投机"改为"值得做但最后做、默认关"）。
- **补充信息可见性前提（§1.2）**：协议 §7 双方 `players[]` 全字段可见（全信息对抗），对手投影数据可行；唯一不可观测的是对手意图，故靠 confidence 表达。
- **新增分数质量地板（§1.3 + §3.3 + 设计铁律）**：`_can_afford` 只守时间不守分数；新增 `ΔEV≥0`（用 `core/rules.py` 估算净收益）作为所有增量动作的第二道与门，防 AGGRESSIVE 重演 839cfc9 过度贪任务/烧好果的败局。
- **档位调参收敛**：AGGRESSIVE 绕路上限从直觉 120 收敛到 90（§5.1、§9）；新增 `ACTION_MIN_NET_SCORE*` 配置。
- **mode 置信度演化说明（§4.4）**：前段投影噪声大、mode 多停 EVEN，切换主战场在中后段。
- **落地顺序（§10）**：P1 改为"纯观测先行、零风险、不改动作"；新增 P1.5 分数质量地板前置于任何改动作层；补 `test_net_score_delta.py`（§11）。

### Changed（规格文档）
- `CLAUDE.md`：能力矩阵新增"对手投影驱动的风险档位切换（博弈层，❌）"；Roadmap 新增 M8；已知限制新增三条（mock 交付帧≠实战、安全地板只守时间不守分数、`world.opponent` 尚未驱动决策）；更新迭代日志与头部日期。

### Verified
- 未改运行期代码；无需回归。设计与协议 §7、`core/rules.py` 公式、Iteration 8 历史教训逐条核对一致。


## [Iteration 9] - 2026-07-02 — 交付件工程重构（提交格式对齐 + trace 日志 + 移除 analysis/打包脚本）

### 触发
`client/` 需**直接充当**提交平台交付件 ZIP 的根目录；日志需随交付件取回并可被 Claude Code 直接分析，不再依赖 python 分析模块。

### Changed（交付件结构）
- `start.sh` 从仓库根**移入 `client/`**，与 `main.py` 同级（即 ZIP 根）；**删除脚本内全部中文注释**（改英文），指向同目录 `main.py`；保留可执行位（git 100755）。
- `client/` 本身即交付件根目录：手动打包时把 `client/` 的**内容**压成 ZIP（`start.sh` 直接位于 ZIP 根，不套同名目录）。

### Changed（日志：logger/match_logger.py、main.py、communication/tcp_client.py）
- `MatchLogger` 由结构化 JSONL 改为**人类可读 trace**：每行 `<时钟> <Event> matchId=..., round=..., k=v`，逐行 flush；文件 `client/logs/match_<matchId>_<playerId>.log`。
- 日志落**包内** `client/logs/`：`main.resolve_log_dir()` 改为相对 `client/` 目录解析（原为项目根）。
- main 全量改用语义化 `trace()` 事件：Startup/Register/Start/Ready/Frame/Action/Recv/Error/Over/Score/Shutdown；每个动作一行 `Action ... action=MOVE, target=S05`，空动作显式记 `action=NONE, note=heartbeat`；仅超决策预算才附 `ms`。over 结算拆为 `Over`（含 iWon）+ 逐队 `Score`。

### Removed
- 删除 `analysis/` 整个 python 分析模块（parser/evaluator/optimizer/report + 其单测）——分析改由 Claude Code 直接读 trace。
- 删除 `scripts/build_zip.py`、`scripts/build_zip.sh` 与 `dist/`——打包改为人工。

### Added
- 仓库 `logs/`（client 之外）作为**采集/分析目录**：取回的 trace 日志入库供 Claude 直接分析；新增 `logs/README.md` 说明采集流程与 trace 格式。
- `client/logs/.gitkeep`（运行期日志目录占位）。

### Changed（工程配置与文档）
- `.gitignore`：移除 `logs/**/*.jsonl` 与 `dist/`；改忽略 `client/logs/*.log`（保留 `.gitkeep`），仓库 `logs/*.log` 入库。
- 刷新 `CLAUDE.md`（§2 架构 / §3 原则 / §4.4-4.5 能力矩阵 / §7 迭代日志）、`README.md`（目录结构）、`docs/architecture.md`、`docs/delivery_spec.md`。

### Verified
- client 单测 96 全通过。
- 端到端（`py client/main.py` 对 `scripts/mock_server.py`）：`DELIVER @round 48`，trace 日志正确落在 `client/logs/match_mock_match_001_1001.log`（Startup→…→Over/Score/Shutdown）。
- `git ls-files --stage client/start.sh` = 100755（可执行）。


## [Iteration 8] - 2026-07-02 — 修复交付前卡死（保证交付）

### 触发与更正诊断
真实对局 `local-debug-l1`（`logs/match_local-debug-l1_1001.analysis.md`）**未交付败北**：末帧 **S14/WAITING**，
一直卡到第 600 帧。**并非超时**（上一版误诊为过度做任务），而是**在交付点前的某位置停滞不动**。
根因：`decide()` 把 `MOVING/WAITING` 当作被动状态，只回空动作 `[]` 且从不重新规划；真实服务端在路线边收到空动作会把车队
park 成 `WAITING` 且不前进——于是验核完成后车队停在 S14/WAITING，永远不再发 `MOVE`/`DELIVER`，直到比赛结束。
（此前 mock 在空动作时仍自动推进，故一直掩盖了该 bug。）

### Changed（strategy/decision.py）
- 新增 `_keep_moving`：`MOVING/WAITING` 每帧**主动续行**——重发 `MOVE` 到当前目标节点（协议允许，不改道、不清进度）；
  若无在途目标（被报为等待却停在节点）则按节点空闲**重新规划**。**杜绝任何交付前位置的空等卡死。**
- 回退上一版基于"超时"误诊的交付冲刺模式与"任务上限停止机会式做任务"（保留 `TASK_SEEK_TARGET=90` 仅限制"为任务绕路"上限）。
- 保留严格交付判定：到 S15 且已验核、好果>0、鲜度>0 立即 `DELIVER`。

### Changed（scripts/mock_server.py）
- 真实化路线边行为：`MOVING/WAITING` 下只有主动续行(MOVE 到当前目标/马类)才前进，空动作会 park 成 `WAITING`——
  用于**复现该卡死并防回归**。

### Changed（analysis/optimizer.py）
- 未交付且末态为 `WAITING/MOVING` → 诊断为"交付点前停滞"，建议主动续行+到点即交付（替换上一版的超时误判建议）。

### Verified
- 单测 96（client）+ 5（analysis）全通过（含新增 `TestNeverStuck`：移动续行/等待恢复/宫门重规划验核/终点交付）。
- 端到端（faithful mock，会 park WAITING）：客户端**不再卡死**，`DELIVER_SUCCESS @round 48`（好果 100、任务 60、鲜度 97.6）。


## [Iteration 7] - 2026-07-02 — 能力补全（补齐部分/未实现能力）

### Added（strategy/decision.py，均在"稳定交付"硬约束下）
- **错误码分类 + 拒绝反馈**：读上一帧 actionResults/events；`PROCESS_REQUIRED` → 强制在当前节点先处理；移动阻塞类(MOVE_BLOCKED_BY_GUARD/TARGET_NOT_REACHABLE/MOVE_EDGE_NOT_FOUND/OBJECT_BUSY) → 临时拉黑目标节点(REJECT_BLOCK_ROUNDS)并绕行，防止重复撞同一阻塞。
- **情报(INTEL)探路**：向前方处理点/宫门（射程 15 内）用情报减处理帧；领取带"可用性守卫"`_intel_usable_ahead`（前驱入边距离≤15 才领，避免长边地图领取无法使用的情报）。
- **绕行 vs 清障权衡**：绕行比就地清障多 `REROUTE_VS_CLEAR_EXTRA` 帧以上且直路下一跳是可清障障碍时，改为就地清障。
- **绕路做任务**：任务分<90 且时间预算允许时，向近处任务节点绕行（`TASK_DETOUR_MAX_EXTRA_FRAMES` 上限）以拉高任务分/解锁满额送达。
- **防御性小分队**：路径第 2 跳后的障碍 → `SQUAD_CLEAR` 预清；敌方有效设卡 → `SQUAD_WEAKEN`（省主车队好果/时间）。
- **主动设卡（进攻）**：关键关隘 `SET_GUARD`，`config.ENABLE_OFFENSIVE` 默认关闭。
- `config.py`：M7 常量。`client/tests/test_advanced.py`：10 项单测。

### Changed
- `scripts/mock_server.py`：支持 `USE_RESOURCE INTEL`(即时落标记)、探路标记减 PROCESS 帧、`SQUAD_CLEAR` 延迟清障、接受 `SQUAD_WEAKEN/REINFORCE`。

### Verified
- 单测 96/96 通过（client 91 + analysis 5）。
- 端到端：小分队预清 S13 障碍(OBSTACLE_CLEAR)，主车队免耗好果 → 交付好果保 **100**（M5 为 99）；情报在长边地图正确地不领取；`DELIVER_SUCCESS @round 48`（早于 M5 的 r55）。

### Notes / 保留的取舍
- 进攻干扰默认关闭（delivery-first，正收益未验证）。
- 情报在当前竞技地图（各边>15）不生效，属地图特性。


## [Iteration 6] - 2026-07-02 — 分析闭环与打包

### Added
- `analysis/`：赛后日志分析框架（四件套 + CLI）。
  - `parser.py`：JSONL → 结构化对局数据（追加日志只取最近一次会话）。
  - `evaluator.py`：交付/得分/鲜度/任务分、决策耗时、动作/事件分布、错误/异常统计，及优点/问题/风险。
  - `optimizer.py`：评估 → (方向,问题,建议) 列表（未交付/任务<90/鲜度低/超时/异常/交付偏晚等启发式）。
  - `report.py` + `__main__.py`：渲染 `analysis.md` 落盘；`python -m analysis <log|dir>`。
  - `analysis/README.md`、`analysis/tests/test_analysis.py`（5 项）。
- `scripts/build_zip.py`(+`build_zip.sh`)：打包提交 ZIP（根含可执行 start.sh + client/，排除 tests/pycache）并执行 §10.7 自检：可解压、根含 start.sh、可执行位、3 参数、含 main.py、纯标准库(无第三方 import)、无现场安装命令、无硬编码 IP。

### Changed
- `client/main.py`：每帧新增 `frame` 日志（本方 node/state/freshness/goodFruit/taskScore/verified/delivered + 事件类型），解析与决策异常分别记录；**修复日志 bug**：`summarize_over` 补齐 deliverRound/freshness/goodFruit/taskScore/bountyScore/scoreDetail，使赛后能读到最终结算明细。
- `.gitignore`：忽略 `dist/`。

### Verified
- 单测 86/86 通过（analysis 5 + client 81）。
- 真实日志端到端：对 M5 仿真日志运行 `python -m analysis`，正确产出 `analysis.md`（交付回合 55、好果 99、鲜度 97.25、任务分 60，动作/事件分布完整，0 异常）。
- `build_zip.py`：产出 `dist/gameclient.zip`（19 个 client 文件），§10.7 自检全部 PASS。

### Next (M7+)
- 接入真实对局日志迭代优化；可选增强：绕路做任务、情报探路、绕行 vs 清障代价权衡、主动干扰(设卡/小分队清障削弱)。


## [Iteration 5] - 2026-07-02 — M5 对抗策略

### Added
- `core/game_map.py`：`time_optimal_path(..., blocked=...)`——跳过进入被阻塞节点的边，实现绕行。
- `strategy/decision.py`（叠加于 M4，稳定交付仍硬约束）：
  - 阻塞感知推进 `_advance`：把道路障碍/敌方有效设卡节点视为不可进入，优先绕行；无法绕行时突破。
  - 突破 `_breakthrough`：障碍→T04(得分+清障)/CLEAR(耗好果，保留最低好果)/FORCED_PASS；敌卡→`_plan_attack`(最小投入达防守值，RUSH 绑破关令 +3)否则 FORCED_PASS。
  - 窗口出牌 `_window_card`：本方参与窗口时按可支付牌(兵争>献贡>验牒>强行)否则弃权。
  - 终局急策：低鲜度护果令；有畅通去路且远且无马时疾行令（被阻挡时不浪费疾行令）。
  - 小分队探路宫门 `_maybe_squad`：普通阶段临近宫门(帧数窗口内)派探路，减少验核 3 帧。
- `config.py`：M5 常量（保留最低好果、宫门探路帧窗口）。
- `tests/test_combat.py`：14 项对抗单测（绕行/突破障碍/突破设卡/窗口牌/急策/探路）。

### Changed
- `scripts/mock_server.py`：加道路障碍(默认 S13，终段唯一通路)、主车队清障 CLEAR、小分队探路与落地标记、验核减时；每帧下发 hasObstacle 与 scouted。

### Verified
- 全部单测 81/81 通过。
- 端到端仿真：障碍位于 S13(不可绕行)→客户端从 S12 `CLEAR` 清障(好果 100→99)后继续；沿途派 `SQUAD_SCOUT S14`，标记落地使宫门验核 6→3 帧；`DELIVER_SUCCESS @round 55`(鲜度 97.25、好果 99、任务分 60)。退出码 0，未退赛。

### Known limitations
- 基线不主动 SET_GUARD、不主动派小分队清障/增援/削弱、不主动发起窗口争夺（能力已具备，未驱动）。
- 绕行 vs 清障的代价权衡、绕路做任务、情报探路减时属后续优化。

### Next (M6)
- 日志分析闭环：`analysis/` 四件套（parser/evaluator/optimizer/report）解析 `logs/` JSONL，产出 `analysis.md`，回写基线；`scripts/build_zip.sh` 打包与 §10.7 自检。


## [Iteration 4] - 2026-07-02 — M4 收益策略

### Added
- `core/game_map.py`：`time_optimal_path`（按帧数最短路，边权含目标节点固定处理耗时；宫门 VERIFY 不计入路线差异）。
- `strategy/decision.py`（在 M3 之上叠加，稳定交付仍是硬约束）：
  - 路由改用 `time_optimal_path`。
  - 机会式 `CLAIM_TASK`：目标即当前节点、非 T04/T06、非对方保护/占用、且过时间预算守卫。
  - 机会式 `CLAIM_RESOURCE`：缺冰鉴则领冰鉴；无马且离终点远则领马。
  - 鲜度管理：鲜度 < 阈值且持冰鉴 → `USE_RESOURCE ICE_BOX`。
  - 加速：移动中无移动增益且离终点远且持马 → `USE_RESOURCE` 马。
  - 护果令：RUSH 阶段鲜度偏低且未用急策 → `RUSH_PROTECT`。
  - 时间预算守卫 `_can_afford`：做额外读条后仍能在 600 帧内交付才做。
- `config.py`：策略调参常量（冰鉴阈值/马距离阈值/护果令阈值/安全余量/跳过任务模板）。
- 单测：`test_router.py`(3)、`test_economy.py`(14)。

### Changed
- `scripts/mock_server.py`：扩展仿真——资源库存与 `CLAIM_RESOURCE`、皇榜任务与 `CLAIM_TASK`、`USE_RESOURCE`（冰鉴回鲜、马登记 buff）、`RUSH_PROTECT`、buff 衰减与护果令鲜度系数；每帧下发 nodes 库存与 tasks。

### Verified
- 全部单测 67/67 通过。
- 端到端仿真：时间感知路由选择山路（绕开 S02/S04/S05 处理站点，更快），沿途领取冰鉴@S06、短程马@S08 并在移动中用马，完成 S11/S13 任务，`DELIVER_SUCCESS @round 51`（早于 M3 的 r60），鲜度 97.45、好果 100、任务分 60。退出码 0，未退赛。

### Known limitations
- 任务仅"机会式不绕路"：路线外任务不做（仿真中 S09 任务因走山路被跳过）。绕路做任务/情报探路减时属后续优化。
- 未处理设卡/障碍/窗口/小分队与 疾行令/破关令（M5）。

### Next (M5)
- 对抗：设卡/攻坚破卡/强制通行/窗口出牌/小分队，及 疾行令/破关令；遇阻（障碍/敌方设卡）的绕行或突破。


## [Iteration 3] - 2026-07-02 — M3 基线策略

### Added
- `strategy/decision.py`：M3 基线策略。空闲态按"到终点最短路"推进；到固定处理站点先 `PROCESS`（离站前必处理）；到宫门 S14 在 `RUSH` 阶段 `VERIFY_GATE`；验核后进入 S15 满足条件 `DELIVER`。非空闲态/已交付发空心跳。处理完成跟踪：`PROCESS_COMPLETE` 事件或 `PROCESSING→IDLE` 跃迁。
- `core/game_map.py`：新增 `process_nodes` 解析（gameplay.processNodes 或顶层 processNodes）。
- `client/tests/test_strategy.py`：10 项基线策略场景单测。

### Changed
- `scripts/mock_server.py`：升级为**全流程仿真**——加载 `samples/map_config.json` 构建 start，模拟主车队移动/固定处理/宫门验核/交付，到 S14 触发 RUSH，交付即下发 over。

### Verified
- 全部单测 50/50 通过。
- 端到端仿真：客户端自主走完 S01→(水路)→…→S13→S14 验核→S15，`DELIVER_SUCCESS @round 60`（鲜度 97、好果 100），退出码 0，未退赛。
- 校验寻路：Dijkstra 正确选择更省移动量的水路（S02→S04→S05→S09=142600 < 官道 172500）。

### Known limitations
- 仅按移动量选路，未计入固定处理耗时/资源/任务收益（M4）；未处理设卡/障碍/窗口，遇阻会重复 MOVE 被拒（M5）。

### Next (M4)
- 收益策略：资源领取/使用（冰鉴/马/护果令）、皇榜任务取舍、鲜度管理，并让路由考虑处理耗时与收益。


## [Iteration 2] - 2026-07-02 — M2 核心镜像

### Added
- `client/core/rules.py`：规则公式镜像（纯函数）——到站移动量/每帧推进/单边耗时、天气通行倍率、鲜度损耗与转坏阈值、设卡防守值与强制通行时间税、攻坚值、送达/好果/鲜度/用时/任务里程碑/悬赏得分（任务书 §2.3/§3.2/§6/§7）。
- `client/core/pathfind.py`：Dijkstra 最短路 + 路径回溯。
- `client/core/game_map.py`：`GameMap` 从 start 解析 nodes/edges/roles（roles 支持 `map.gameplay.roles` 或按节点类型/ safeZones/reverifyNode 推断），提供相邻/边/到站移动量/最短路（按移动量或路线距离）/到宫门距离；单向边按方向、`bidirectional` 缺省 True。
- `client/core/world_state.py`：`WorldState` 从 inquire 解析 `me`/`opponent`(PlayerView)、`node_states`(NodeState)、tasks/contests/bounties/weather/events/actionResults，提供 active_tasks/my_contests/active_weather/distance_to_gate 等便捷访问。
- 单测：`test_rules.py`(15)、`test_pathfind.py`(3)、`test_game_map.py`(10，含加载 `samples/map_config.json` 真实地图)、`test_world_state.py`(6)。

### Changed
- `strategy/decision.py`：`GameContext` 改为构建 `GameMap`；`DecisionEngine.decide(world)` 接收 `WorldState`（M2 仍返回空动作心跳）。
- `main.py`：每帧构建 `WorldState(data, playerId, game_map)` 后传入 `decide`；解析异常同样降级为空心跳。

### Verified
- 全部单测 40/40 通过。
- mock_server ↔ client 端到端回归通过：每帧解析 WorldState 不影响 registration→over 闭环，退出码 0，未退赛。

### Next (M3)
- 基线策略：最短路推进 → 站点处理(PROCESS/DOCK) → 宫门验核(RUSH) → 交付(DELIVER)，实现稳定交付得分。


## [Iteration 1] - 2026-07-02 — M1 通信打通

### Added
- `client/protocol/`：`framing.py`（5 位长度前缀编解码 + 半包/粘包/中文跨包 FrameDecoder）、`enums.py`（动作/资源/牌/状态/错误码等枚举）、`messages.py`（registration/ready/action 构造 + 下行访问）、`actions.py`（全动作构造器）。
- `client/communication/tcp_client.py`：阻塞 socket + 双线程（接收线程拆帧入队，主线程决策发送），连接/超时/断线处理。
- `client/logger/match_logger.py`：JSONL 结构化日志，落 `logs/match_{matchId}_{playerId}.jsonl`，start 前缓冲、bind_match 后 flush。
- `client/strategy/decision.py`：占位 `DecisionEngine`（空动作心跳）+ `GameContext`（开局静态缓存）。
- `client/config.py`：集中配置（超时、决策预算、日志目录、调试开关）。
- `client/main.py`：启动闭环（解析 argv → registration → start → ready → inquire/action 循环 → over），单帧异常/超时降级为合法心跳。
- `start.sh`：根目录、LF、可执行，透传 `playerId host port`。
- `scripts/mock_server.py`：本地假服务端（协议合法下发，附录 A 默认地图）。
- `client/tests/test_framing.py`：7 项 framing 单测。
- `samples/`：参考样例目录。`map_config.json`（中等难度竞技地图原始配置，经远端合入）已就位；`README.md` 记录其结构、与协议 `start` 的字段差异，并标注 `start_message.json`/`inquire_message.json` 暂不提供（结构以通信协议 §5/§7 为准）。
- `.gitignore`：忽略 `__pycache__`、运行时 `logs/**/*.jsonl` 与本地 `.claude/` 设置。

### Verified
- framing 单测 7/7 通过。
- 端到端：mock_server ↔ client 跑通 `registration→start→ready→8×(inquire/action)→over`，client 退出码 0，全程发 `[]` 心跳、未退赛；日志完整落盘。

### Next (M2)
- `core/`：WorldState 解析 + 地图/寻路（Dijkstra）+ 规则公式镜像 + 单测。

## [Iteration 0] - 2026-07-02 — 文档基线

### Added
- `CLAUDE.md`：项目能力基线（SSOT），含能力矩阵、工作原则、Roadmap、迭代日志。
- `docs/architecture.md`：分层架构、模块职责、数据流、关键技术决策、里程碑。
- `docs/delivery_spec.md`：交付件规格基线（功能/协议/性能/工程/得分导向/自检清单，含验收勾选框）。
- `docs/protocol.md`：通信协议实现速查摘要（指向原始协议文档）。
- `docs/task.md`：任务书实现速查摘要（指向原始任务书）。
- 目录骨架：`client/`（communication/protocol/core/strategy/logger/utils/tests）、`analysis/`、`logs/`、`scripts/`。

### Decided
- 运行期 Client 使用 **Python 3.12.9 + 纯标准库**，零第三方依赖。
- IO 模型：**阻塞 socket + 双线程**（接收线程按 5 位长度前缀拆帧入队，主线程决策发送）。
- 运行期（`client/`）与开发期（`analysis/`）严格分离，提交包纯净、离线可跑。
- 策略与通信解耦：`strategy` 仅依赖 `core.WorldState`。
- 健壮性优先：任何异常/超时均发出合法心跳（空 actions），杜绝因缺动作退赛。

### Next (M1)
- 实现 `communication` + `protocol` + `logger` + `scripts/mock_server.py` + `start.sh`，对 mock 跑通 registration→over 空跑。
