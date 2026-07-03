# CHANGELOG

本文件记录每轮迭代的能力变化。格式：轮次 / 日期 / 变更摘要。能力矩阵与迭代明细见 `AGENTS.md`。

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
- `AGENTS.md`：能力矩阵新增"对手投影驱动的风险档位切换（博弈层，❌）"；Roadmap 新增 M8；已知限制新增三条（mock 交付帧≠实战、安全地板只守时间不守分数、`world.opponent` 尚未驱动决策）；更新迭代日志与头部日期。

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
- 刷新 `AGENTS.md`（§2 架构 / §3 原则 / §4.4-4.5 能力矩阵 / §7 迭代日志）、`README.md`（目录结构）、`docs/architecture.md`、`docs/delivery_spec.md`。

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
- `AGENTS.md`：项目能力基线（SSOT），含能力矩阵、工作原则、Roadmap、迭代日志。
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
