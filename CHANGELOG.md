# CHANGELOG

本文件记录每轮迭代的能力变化。格式：轮次 / 日期 / 变更摘要。能力矩阵与迭代明细见 `CLAUDE.md`。

## [Iteration 20] - 2026-07-05 — 0705 真机回退根因修复：拒绝反馈全覆盖 + 协议动作额度合规 + 交付告急保交付

### 触发
0705 平台 37 场真机归因（`reports/20260705_corpus.md`）：胜率 11/37、**交付仅 20/37（17 场未交付）**、REJECT_LOOP 37/37、EST_OVER_BUDGET 35/37——相较 0704（7/7 交付、3/7 胜）灾难性回退。逐场归因 + 代码核验定位三类根因：
1. **INVALID_ACTION_CONFLICT ×201**（090812 场）：`_keep_moving` 用马时同帧并发 `[horse, MOVE(next)]`（Iter18 P3 引入），但协议 §4.1 明确"每帧最多 1 个主车队动作"，USE_RESOURCE 与 MOVE 同属主车队动作 → 服务端拒其一。Iter18 称"mock 验证"无效——mock 恒 accept。
2. **TASK_REQUIREMENT_NOT_MET ×129 / WINDOW_DRAW_RETRY_LIMIT ×105 / OBJECT_BUSY ×130**：`_apply_rejection_feedback` 只处理 PROCESS_REQUIRED 与 MOVE+4 个移动阻塞码，对其余码完全裸奔 → 客户端每帧重发同一被拒动作至 600 帧（CLAIM_TASK×142 被拒 129、USE_RESOURCE×202 被拒 201、WINDOW_CARD×177 被拒 105），吃光帧预算致未交付。
3. **EST_OVER_BUDGET 35/37**：预算告警时仍持续做收益/窗口循环，无"保交付"模式。

### Changed（`client/strategy/decision.py`、`client/config.py`、`client/tests/test_advanced.py`）
- **P1 协议动作额度合规（INVALID_ACTION_CONFLICT 根因）**：`_keep_moving` 用马时改回 `[horse]` 单动作（用马本帧不 MOVE，下帧 buff 生效后续行 MOVE，至多 1 帧"读条"代价，不构成 Iter8 park 死循环）。新增 `_dedup_actions` 防御性兜底：每类动作（主车队/小分队/急策/窗口）同帧≤1，超额丢弃保留首个，防任何路径回归产出 `[horse, MOVE]` 式非法并发。
- **P0 拒绝反馈全覆盖**：`_apply_rejection_feedback` 重写，`_my_reject_code`→`_my_reject_codes`（收集上帧所有拒绝码）按码分类记忆：
  - `TASK_REQUIREMENT_NOT_MET`/`TASK_NOT_FOUND` → 拉黑 taskId（`_task_blacklist`），`_maybe_task`/`_task_detour_target`/`_find_clear_obstacle_task` 跳过；
  - `OBJECT_BUSY`（非 MOVE）→ 节点忙冷却（`_node_busy_until`），`_maybe_claim` 与 `_plan` process 步跳过；
  - `WINDOW_DRAW_RETRY_LIMIT` → 窗口弃权（`_abstain_contests`），`_my_active_contests` 过滤；
  - `INVALID_ACTION_CONFLICT`/`MOVING_ACTION_FORBIDDEN`/`RESTING_ACTION_FORBIDDEN` → 主动作退避 1 帧（`_action_block_until`），`_freshness_rescue`/`_maybe_horse`/`_maybe_intel`/`_maybe_task` 跳过。
  新增 `_last_window_cid` 跟踪窗口拒绝归因。
- **P2 交付告急保交付**：新增 `_delivery_panicking`（est + 通用余量 > 剩余帧，或路径不可达）。告急时禁用冰鉴绕路/任务绕路、未验核则无论帧数先去宫门、窗口出牌弃权省成本。at-node 冰鉴领取豁免保留（2 帧 < 3.6 分/果，交付鲜度保险）。
- **config**：新增 `WINDOW_ABSTAIN_ROUNDS = 6`。
- **测试**：新增 `TestRejectionFeedbackIter20`（4 项：task 黑名单/窗口弃权/节点忙/动作退避）、`TestProtocolActionQuota`（2 项：用马单动作/dedup 去重）、`TestDeliveryPanic`（1 项：告急禁绕路）。client 157→164 全通过；mock 端到端交付@r498 fresh=89.30 good=96 task=150（与 Iter19 基线一致，无回归），trace 0 错误 0 拒绝。

### 验证
mock 端到端：r374 `MOVING+USE_RESOURCE`（单动作用马）→ r399 抵达 S12（马增益生效、续行正常，无 park 死循环）；r364 `CLAIM_TASK,WINDOW_CARD`、r443 `PROCESS,SQUAD_SCOUT` 跨类别组合合法保留。交付@r498 fresh=89.30 good=96 task=150，预算 est=2 left=102 健康。

**拒绝码仿真端到端**（`scripts/mock_server.py` 增 `_validate_actions`+`last_action_results`，`build_inquire` 发 `accepted=False`+`errorCode`）：
- 默认运行 0 拒绝 → P1 dedup 生效（每帧≤1 主车队动作，无 INVALID_ACTION_CONFLICT）。
- `MOCK_REJECT_TASK=TK2`：CLAIM_TASK 仅被拒 **1 次**（旧版会重发 142 次致未交付），客户端拉黑 TK2 后切到其它任务，交付@r491 task=120。
- `MOCK_REJECT_RESOURCE=S03:ICE_BOX`：CLAIM_RESOURCE 仅被拒 **1 次**（旧版会重发 130 次），节点忙冷却生效，交付@r495 fresh=80.88 good=97 task=150。

### 取舍 / 后续
- mock 拒绝码仿真已补 INVALID_ACTION_CONFLICT（常开）/TASK_REQUIREMENT_NOT_MET/OBJECT_BUSY（env 注入）；WINDOW_DRAW_RETRY_LIMIT 仍未仿真（窗口争夺蓝方刻意偏弱，平局冷却为次要保真项，按需补）。
- `_task_blacklist` 为本局永久拉黑（镜像可做性与服务端不一致不会自愈）；若真机出现误拉黑可改按 taskId+round 窗口拉黑。
- 真机回归重点确认：① 17 场未交付清零；② REJECT_LOOP 37/37 消失；③ 任务分回升（P0 task 黑名单让客户端切到可做任务而非空转）。

## [Iteration 19] - 2026-07-04 — 低筹码窗口 BING 解禁：补红方 RESOURCE/DOCK 出牌能力

### 触发
Iter18 博弈审查暴露的策略缺口（mock 窗口仿真验证时发现）：`_allow_bing` 对 stakes1(RESOURCE/DOCK)一律 False，而红方不领 PASS_TOKEN/OFFICIAL_PERMIT（`_maybe_claim` 不覆盖）、马只领 1 匹（领到即 `_has_any_horse=True` 不再领第二匹），故 stakes1 下 BING(`_allow_bing=False`)/XIAN(`allow_xian` 要 stakes>=2) 全关、YAN 无过所、QIANG 需马且输 YAN/BING → 几乎只能 ABSTAIN → 低筹码窗口必输。

### Changed（`client/config.py`、`client/strategy/decision.py`、`client/tests/test_combat.py`、`scripts/mock_server.py`）
- **P1 `_allow_bing` 低筹码解禁**：新增 stakes1 分支——`guard > WINDOW_BING_LOW_STAKES_RESERVE`(默认 2) 时解禁 BING。BING 胜 YAN/QIANG、平 BING、仅负 XIAN，是低筹码下红方唯一能赢/平的牌（XIAN 需鲜度≥80+好果，stakes1 仍关；YAN 需过所，红方不领）。保留 2 点给中/高筹码窗口（stakes2 需 g>1、stakes3 需 g>=1），故低筹码仅在 g>=3 时花，最多花 2 次（4→3→2）。
- **P2 config**：新增 `WINDOW_BING_LOW_STAKES_RESERVE = 2`。
- **P3(mock) RESOURCE 触发**：`WINDOW_TRIGGERS` 加 `("S03","CLAIM_RESOURCE","ICE_BOX")`，端到端验证低筹码窗口出牌（Iter19 前 RESOURCE 不触发因红方无牌可出）。
- **测试**：`test_no_bing_on_low_stakes_resource`(gp=4→BING) 与 `test_resource_window_no_bing_even_with_guard`(gp=4 fresh=70→BING) 翻转；新增 `test_no_bing_on_low_stakes_when_guard_reserved`(gp=2→ABSTAIN)。client 156→157，analysis 23 不受影响。

### 验证
mock 端到端：S03 RESOURCE 窗口 1-0 胜（r86 BING 领出平→r87 BING 胜蓝弃权→r88 ABSTAIN(g=2 保留)平，获 ICE_BOX），S11 TASK 窗口 2-0 胜，交付@r498 fresh=89.30 good=96 task=150。

### 取舍 / 后续
- 低筹码花 guard 的机会成本：RESOURCE 胜得资源(ICE_BOX≈3.6 分)，guard 点留给 GATE 验核权。reserve=2 平衡（最多花 2 次，保留 2 给中/高）。真机回归若低筹码耗光 guard 致 GATE 窗口无 BING，上调 `WINDOW_BING_LOW_STAKES_RESERVE`(2→3，仅 g=4 时花)。
- g 级联：低筹码 contest 耗 guard 后，后续 TASK contest 可能用 XIAN 替 BING（多耗 1 好果）。mock 实测 TASK beat3 改 XIAN（good 多耗 1），可接受。
- `WINDOW_MIXED_LEAD` 仍待 mock 蓝方改强对手压测后启用。

## [Iteration 18] - 2026-07-04 — 博弈审查驱动：多窗口优先级/马匹统一预算/出牌反剥削/路由一致/死代码清理

### 触发
对 `client/strategy/decision.py` 做博弈算法视角审查，发现 8 类结构性问题。本轮实现其中 7 项（第 8 项瞬时拒绝重试暂缓）：
1. 窗口同帧只出 1 张（协议§5.4.2）时纯按筹码排序 → 紧迫窗口（决胜拍/deadline 临近）被弃权丢胜点。
2. 马被加速/QIANG/T06 三处独立消耗无全局预算 → 窗口 QIANG 可吃掉前方 T06(+30 分)的马；同帧加速+QIANG 双扣。
3. `_keep_moving` 用马时本帧不发 MOVE → 真实服务端在路线边收到非 MOVE 动作会 park 成 WAITING（已修过的卡死模式复发风险）。
4. `_BEATS[YAN_DIE]` 反制序 XIAN 先于 BING → 好果(直接换交付分)被优先消耗，护卫点(无其他用途)机会成本更低却排在后。
5. `_can_break`（路由代价估算）不含破关令 +3，与 `_plan_attack`（实际攻坚）不一致 → RUSH 阶段 [best, best+3] 区间误判不可破、误绕远路。
6. R1 领出纯确定性 → 鲜度≥80 时恒领 BING 被反应式对手针对（领 XIAN 稳吃）。
7. `_triggered`/`_track_freshness`/`_next_untriggered_threshold`/`_prev_freshness` 自 Iter15 起不驱动任何决策却每帧运算；config 三个兼容常量 `ICE_BOX_USE_BELOW/ICE_BOX_LEAD/ICE_BOX_HOT_USE_BELOW` 无引用——死代码误导后续调参。

### Changed（`client/config.py`、`client/strategy/decision.py`）
- **P1 多窗口优先级**：`_my_active_contests` 排序键由纯 `_stakes` 改为 `_contest_priority` = 筹码×100（主导）+ 速胜关门价值(任一方达 1 胜点 +6) + 后拍紧迫(roundIndex) + deadline 临近(剩余响应帧≤1 +8)。避免紧迫窗口被高筹码窗口挤掉而弃权。
- **P2 马匹统一预算**：`_window_card` 计算 `reserve_horse`（本帧马已被加速占用 OR 去路上有需马的活跃 T06 且任务分未封顶），传入 `_available_cards` 新增形参；QIANG 在无移动增益且 `reserve_horse` 时不进入可用牌，保留马给 T06/加速。已有 buff 时 QIANG 免消耗不受影响。
- **P3 `_keep_moving` 用马同帧补 MOVE**：返回 `[horse, actions.move(next_node_id)]`（不同动作类别不互占额度，§4.1），杜绝用马导致 park 卡死；无在途目标时仍只返回 `[horse]`。mock 端到端 r370 验证 `act=USE_RESOURCE,MOVE` 同帧处理未卡。
- **P4 反制成本排序**：`_BEATS[YAN_DIE]` 由 `(XIAN_GONG, BING_ZHENG)` 改为 `(BING_ZHENG, XIAN_GONG)`——反制对手 YAN 时优先用 BING(护卫点，机会成本低)，BING 不可用时回落 XIAN。`_allow_bing` 已按筹码分级开关，低筹码自然回落 XIAN。
- **P5 路由一致**：`_enter_cost_fn` 计入 RUSH 未用急策时的破关令 +3 bonus 传入 `_can_break`（新增 `bo_bonus` 形参），与 `_plan_attack` 实际攻坚能力对齐，消除 RUSH 阶段直行代价高估导致的误绕路。
- **P6 混合领出（反剥削 lever）**：新增 `config.WINDOW_MIXED_LEAD`（默认 False 保单测确定性）。开启后 `_lead_card` 按 BING 0.5/XIAN 0.25/QIANG 0.15/YAN 0.10 权重在可用强牌间混合；roll 由 `contestId+roundIndex+round+playerId` 哈希得，确定性可复现。平台对手若反应式预判我方克制时启用。
- **P7 死代码清理**：移除 `_triggered`/`_prev_freshness` 字段、`_track_freshness`/`_next_untriggered_threshold` 方法及 `_update_process_memory` 中的调用；移除 config 三个无引用兼容常量。`rules.crossed_good_to_bad_thresholds` 保留（纯函数，analysis 可能用）。

### 测试
client 单测 156 项全通过（窗口 5 项 + 其余不变）；analysis 23 项全通过。mock 端到端 `DELIVER_SUCCESS @r494 fresh=89.61 good=98 taskScore=150`，与 Iter16 基线一致，无回归。

### 未实现 / 后续
- 瞬时拒绝（OBJECT_BUSY）的 SET_GUARD/SQUAD 重试：当前"一次拒绝即永久拉黑本节点"对瞬时错误过度保守，但区分错误码重试+重试上限较复杂，暂保留现有防卡死兜底；真机回归若发现有效设卡被瞬时拒绝吞掉再补。
- 确定性出牌在鲜度≥80 仍可被反应式对手针对——启用 `WINDOW_MIXED_LEAD` 可缓解，但需 mock 补全窗口争夺后端到端验证收益再默认开启。
- 冰鉴投影用常数损耗 `FRESHNESS_LOSS_ASSUME`（HOT 天气实际更高）→ 触发偏松，待真机回归校准。

### 补充：mock 窗口争夺仿真（同轮）
`scripts/mock_server.py`（非交付件）原 `"contests": []`，窗口出牌策略从未端到端验证。补全 3 拍窗口争夺仿真：
- **机制**：`WINDOW_TRIGGERS` 触发点 → 创建窗口(WINDOW_CONTEST_START) → 3 拍 WINDOW_CARD_REVEAL 结算(BEATS 表) → WINDOW_CONTEST_END + 胜负授予(RESOURCE/TASK)。`contests_view` 下发 contestId/roundIndex/redPoint/bluePoint/cards(颜色 key)/deadlineRound；蓝方虚拟资源池出牌。
- **牌成本扣减**：BING→护卫点、XIAN→好果、QIANG→马(有 buff 免)、YAN→过所，反映到下一帧 snapshot（红方 guardActionPoint 由硬编码 4 改为 `self.guard_ap` 动态扣减）。
- **`_apply_idle` 守卫**：CLAIM_RESOURCE/CLAIM_TASK 命中活跃窗口时跳过底层读条，由窗口结算后授予（防重复创建/重复读条）。
- **触发点仅 TASK**（`("S11","CLAIM_TASK","TK2")`）：RESOURCE 低筹码不触发——红方不领过所/官凭、马只领 1 匹，stakes1 下几乎无牌可出（策略层真实缺口，不宜用 mock 掩盖）。
- **验证**：mock 端到端 S11 TASK 窗口红方 2-0 胜（r361 BING 领出→r362 XIAN 反制 BING→r363 BING 领出），TASK_CONTEST_WIN→任务读条，交付@r497 fresh=89.38 good=97 task=150。client 156 + analysis 23 单测不受影响。
- **蓝方刻意偏弱**（BING 试一拍即弃权）以保交付稳定；真机对手更强，`WINDOW_MIXED_LEAD` 仍待强对手压测后启用。

## [Iteration 17] - 2026-07-04 — 窗口 PK 必输根因修正：鲜度<80 不弃权、中筹码 BING 解禁+预算预留

### 触发
平台 PK 反馈：**窗口 PK 一直输**。核查协议 §5.4.4 胜负表确认克制表 `_BEATS` 本身正确，根因在出牌策略与成本门控：
1. 中筹码窗口（TASK/OBSTACLE）鲜度<80 时结构性必输——`allow_bing=stakes>=3` 把 TASK/OBSTACLE 挡在 BING 外，`allow_xian` 又要求 `freshness>=80`；真机 7/7 鲜度均值 77.28、普遍<80 → XIAN 不可用 + BING 被禁 → 只能 ABSTAIN → 0-2 输任务窗口、丢 30 分。
2. "无法克制就弃权"在鲜度<80 时是错的——此时 BING 近无敌（唯一克星 XIAN 双方都没有），应继续出 BING 求平/胜，弃权对任何实牌都输。
3. 护卫点（4 点、不恢复、唯一用途=BING）无预算分配，高筹码窗口 BING×3 平局即耗光，之后全部退化必输。
4. `mock_server.py` 完全未实现窗口争夺（仅 `"contests": []`），蓝方为静态 dummy，故窗口策略从未在端到端对抗下被验证——缺陷长期未暴露。

### Changed（`client/config.py`、`client/strategy/decision.py`、`client/tests/test_combat.py`）
- **P1 中筹码 BING 解禁 + 预算预留**：新增 `_allow_bing(me, stakes)`——GATE/PASS(stakes3) 关键窗口 `guard>=1` 即用；
  TASK/OBSTACLE(stakes2) 在 `guard > WINDOW_BING_RESERVE`(默认 1) 时解禁 BING（保留 1 点给潜在 GATE/PASS）；
  RESOURCE/DOCK(stakes1) 不花护卫点。替换旧 `allow_bing = stakes>=3`。
- **P2 鲜度<80 不弃权**：重写 `_window_card` 决策树为 `_choose_card`——有对手上一拍信息时：①优先克制 ②无法克制则出同牌求平
  ③再无法则出 `_strongest_available`（BING>XIAN>QIANG>YAN）争取对手换牌时赢，**而非弃权白送胜点**。
  旧逻辑在"无法克制+无法平"时 ABSTAIN，正是鲜度<80 中筹码窗口 0-2 必输的直接原因。
- **P3 确定性领出**：`_lead_card` 改为按 `(BING, XIAN, QIANG, YAN)` 优先级取首个可用——鲜度<80 时 BING 近无敌优先领 BING；
  低筹码因 `_allow_bing` 关闭 BING 自然回落 QIANG/YAN，与旧行为一致。保持纯确定性以兼容单测。
- **P4 cards key 双兼容**：`_opp_last_card` fallback 在 `cards.get(颜色)` 取不到时用对手 playerId 字符串再取一次，
  兼容服务端以颜色或 playerId 作 key 的两种实现（主路径仍走 WINDOW_CARD_REVEAL 事件）。
- **测试**：现有 5 项窗口单测全部保留通过；新增 5 项覆盖 TASK 鲜度<80 出 BING / 同牌求平 / 护卫点≤reserve 不弃权出 YAN /
  GATE 仅剩 1 点仍出 BING / RESOURCE 不花 BING。client 单测 151→156，analysis 23 不受影响。

### 预期效果
鲜度<80（真机常态）下窗口不再 0-2 空手输：BING 保平或克制取胜；中筹码任务窗口可花护卫点争夺（30 分 > 1 护卫点）；
护卫点按价值（GATE>PASS>TASK）预留。反 exploitation 的混合出牌作为后续可选 lever（需引入随机，暂未启用以保单测确定性）。

## [Iteration 16] - 2026-07-04 — 任务分做不满根因修正：取消 T04/T06 硬编码跳过，改协议动态评估

### 触发
平台 PK 反馈：任务分普遍低于对手，**哪怕对手不动、任务分也做不满 180**。
归因：`config.SKIP_TASK_TEMPLATES = ("T04", "T06")` 按模板 ID 硬编码跳过 2/5 任务模板——
T06（争马换乘，消耗 1 马、3 帧、+30 分）从不做；T04（清障任务）仅在被障碍挡住时才做。
5 模板地图跳过 T04+T06 后最多做 3 任务 = 基础分 90 → 最终任务分 125，**结构性到不了 180**。
且该跳过逻辑按模板 ID 硬编码，地图一变模板失效（用户明确要求"通过通信协议获取地图信息"）。

### 关键认识
- 任务分 = `min(180, 基础分 + 里程碑)`（§7.2），里程碑 ≥110→+50，故**基础分≥130（5 任务）才封顶 180**。
  超过 130 的任务零分收益（任务分已 180、送达基础分在 base≥90 饱和、用时分在 base≥90 饱和），只徒增用时与鲜度损耗。
- 旧 `_task_detour_target` 停止条件 `me.task_score >= 180` 永不触发（`_maybe_task` 在 130 已停），导致 130→180 间做无用绕路。
- T06 +30 分 >> 单匹马的移速收益（~1 用时分），但旧策略把马用于加速，到 T06 节点时已无马可消耗。

### Changed（`client/config.py`、`client/strategy/decision.py`、`client/tests/`、`scripts/mock_server.py`）
- **P1 取消 `SKIP_TASK_TEMPLATES` 硬编码跳过**：改为基于协议模板属性动态判定任务可做性。
  `GameContext` 缓存 `start.taskTemplates` 为 `task_template_map`（taskTemplateId→模板）；
  新增 `_template_of`/`_task_required_resources`/`_task_required_freshness`/`_is_clear_obstacle_task`/
  `_task_at_node`/`_task_claimable_by_me`/`_can_spend_required_resources` 一族纯函数化判定器，
  读 `processType`/`requiredResourceTypes`/`requiredFreshness`/`score`，地图变化自动适配。
- **P2 T06（消耗马任务）可做**：`_can_spend_required_resources` 对马类(FAST/SHORT_HORSE)按"任一持有≥1"判定
  （任务书：消耗 1 个快马或短程马，二选一）。`_maybe_horse` 新增 `_horse_requiring_task_ahead` 守卫——
  去路上还有可达的需马任务且任务分未封顶时，**不为加速消耗马，留给 T06**（30 分 > ~1 用时分）。
- **P3 T04（清障任务）全路径可做**：`_is_clear_obstacle_task` 按 `processType==CLEAR_OBSTACLE` 判定（非模板 ID），
  `_task_at_node` 支持 §5.2"可在障碍节点或相邻节点处理"；`_breakthrough` 中 `_find_t04`→`_find_clear_obstacle_task`；
  `_task_detour_target` 新增 `_clear_obstacle_approach` 为障碍节点选可达相邻点作绕路目的点。T04 优于 CLEAR（+30 分且不耗好果）。
- **P4 任务分封顶修正**：`_task_detour_target` 停止条件由 `me.task_score >= 180` 改为 `_task_score_capped(me)`
  （基础分≥130→180 封顶），杜绝 130 后的无用绕路。`config.TASK_SEEK_TARGET` 150→130（基础分上限，=180 封顶点）。
- **P5 机会式做任务用紧余量**：`_maybe_task` 的 `_can_afford` 由默认 25 改为 `TASK_DETOUR_SAFETY_MARGIN`(15)——
  在节点做任务无绕路成本仅花处理帧，+30 分值得用紧余量释放预算（与绕路同口径）。
- **mock 保真度**：`scripts/mock_server.py` CLAIM_TASK 支持 T04 相邻节点处理（§5.2）+ 完成时同步清障；
  TASKS 增加 T06@S11、T04@S13，taskTemplates 补全 T04/T06 属性。

### 验证
新增 6 项单测（共 151 client + 23 analysis 全通过）：T04 机会式领取/相邻节点领取、T06 持马领取/无马跳过、
封顶 130 不绕路、T06 持马绕路。mock 端到端 5 任务全做（T01@S09/T02@S11/T06@S11/T04@S12 相邻/T01@S13），
**taskScore 90→150（最终任务分 180）**，交付 @r494 fresh=89.61 good=98（鲜度保 80 阈值以上）。
马匹保留验证：SHORT_HORSE 从 S09 持有至 S11 完成 T06 后才用于加速（`_horse_requiring_task_ahead` 生效）。

## [Iteration 15] - 2026-07-04 — 真机 7 场归因驱动：任务分上限对齐对手 180 + 冰鉴使用逻辑修正

### 触发
取回 7 场真机报告（`reports/20260704_*.md` + corpus）：3 胜 4 负，7/7 交付，均交付 469.6 帧、均鲜度 77.28。
4 场负局中 3 场主因任务分缺口（对手稳定 180，我方卡 90/150），2 场小分差负局（113730 -2、120537 -12）
正好 = 任务分 30 分缺口。归因发现两个可调点：

1. **任务分卡 150**：4/7 场任务分恰为旧 `TASK_SEEK_TARGET=150` 上限（非预算/路线限制——对手 180 证明可达），
   单场丢 30 分。Iter13 上调到 150 仍未追平对手 180。
2. **冰鉴使用逻辑过保守**：旧 `_freshness_rescue` 仅在"鲜度距下一未触发阈值 ≤7"时使用，f=89（距 80 阈值 9>7）
   不用 → 整局仅用 1 个冰鉴，余量闲置。

### 关键发现（冰鉴不在最短路，但可绕路收集）
冰鉴仅在 S03/S06/S07（任务书 §3.3），而最短路 S01→S02→S04→S05→S09→S10→S11→S12→S13→S14→S15
**不经过任一冰鉴节点**——这是 7/7 鲜度崩盘（均 77.28）的根因：旧路由器只最小化 time+λ·freshness，
不估值冰鉴，故从不绕路收集，整局 0 冰鉴可用。Iter13 的冰鉴领取豁免在本图为纯 no-op（路线不经过冰鉴节点）。
**但**官道替代路 S02→S03→S07→S09 顺路经过 2 个冰鉴节点（S03、S07），额外 ~35 帧换 +20 偏移，
净鲜度收益 ~+16（远 > ~4 用时分损失）——这是"以时间换鲜度"的真正杠杆（用户诉求）。
关键约束：必须用净鲜度收益过滤排除山路绕路（S06：S01→S06 山路 0.07 损耗，净收益<6 反而拖垮鲜度且丢任务）。

### Changed（`client/config.py`、`client/strategy/decision.py`、`client/tests/`）
- **P1 任务分上限 150→180**（`config.TASK_SEEK_TARGET`）：对齐对手。任务分 1:1 涨至 180（base≥130+里程碑 50 封顶），
  90 以上用时分乘数饱和（`time_score=min(base,90)/90` 封顶），故额外任务仅付原始用时分+鲜度小成本换 +30 任务分。
  `FRESHNESS_DETOUR_FLOOR=65` / `TASK_DETOUR_MAX_EXTRA_FRAMES=70` / `TASK_DETOUR_SAFETY_MARGIN=15` 仍守卫
  不致鲜度崩盘/超时。4 场卡 150 的可在 r360 前置窗口前继续绕路做任务至 180。
- **P2 冰鉴使用逻辑修正**（`decision._freshness_rescue`）：鲜度 ≤`ICE_BOX_CAP_AVOID`(90) 即用，
  替换旧"仅近阈值≤7 使用"。认识：鲜度损耗线性，冰鉴 +10 是交付前**永久偏移**——无论何时使用（交付前），
  最终鲜度都 +10（前提不撞 100 上限）。故最优=持有时尽快在 ≤90 时用，用满 2~3 个叠加 +20~30 偏移。
  移除近阈值/酷暑/紧急三条旧判据（均被 ≤90 覆盖）。`_next_untriggered_threshold` 保留供诊断。
- **P3 冰鉴绕路收集**（`decision._ice_box_detour_target`，用户"以时间换鲜度"诉求）：投影交付鲜度
  (当前+已持冰鉴×10−剩余帧损耗) < `ICE_BOX_DETOUR_PROJECTED_BELOW`(85) 且已持 < `ICE_BOX_DETOUR_KEEP`(2) 时，
  绕路去冰鉴节点收集。筛选条件：冰鉴节点在 `ICE_BOX_DETOUR_MAX_EXTRA_FRAMES`(60) 绕路范围内、
  **净鲜度收益(+10−绕路额外损耗) ≥ `ICE_BOX_DETOUR_NET_MIN`(6)**（用新增 `_path_freshness_loss` 估算路径损耗）、
  时间预算允许（`_can_afford` 25 帧余量）。净收益过滤排除山路绕路（S06：S01→S06 山路 0.07 损耗，净收益<6），
  保留官道绕路（S02→S03→S07→S09，ROAD 0.055，净收益~7）——后者顺路收 2 个冰鉴且不丢下游任务节点（S09 等）。
  置于任务绕路之前（鲜度是交付质量硬约束）。
- **单测**：新增 `test_ice_box_anytime_below_cap`、`test_ice_box_used_repeatedly_as_freshness_decays`；
  更新 `test_no_detour_when_task_score_enough` / `test_detour_when_below_new_cap` 注释为 180。共 146 项通过。

### 验证
- client 146 单测全通过（Iter14 的 144 + 新 2）。
- mock 端到端（净收益过滤后）：路线 S01→S02→**S03**(冰鉴)→**S07**(冰鉴)→S09→S10→S11→S12→S13→S14→S15，
  收 2 个冰鉴并分别于 r164/r350 使用（+20 偏移）→ **fresh 74.79→90.57、good 97→98（保 80 阈值省 1 篒好果）、
  task 90 不变、交付 r459→r482（+23 帧）**。净分 +27（+28 鲜度分 +1.8 好果分 −2.7 用时分）。
  对比未过滤版本（绕山路 S06）：fresh 80.13 但 task 90→60（丢 S09 任务）净 −15——净收益过滤是关键。

### 预期收益与限制
- 预期翻 2 场小分差负局（113730 -2→+28、120537 -12→+11），4 场卡 150 的场均 +30 任务分。
- 鲜度 77→90+ 跨过 80 阈值：省 1 篒好果(+3.6) + 鲜度分 +28（扣抵 +23 帧用时分 ~2.7），4 场鲜度崩盘局显著改善。
- 2 场任务分 90 的负局（120521/120605）为在途任务节点稀疏所致，提升上限不改变。
- 冰鉴绕路依赖地图上冰鉴节点在合理绕路范围内；其他地图若无冰鉴/绕路过远则不触发（自动回退）。

## [Iteration 14] - 2026-07-04 — mock 保真度对齐真机（移动结算/天气/鲜度/好果转坏）

### 触发
Iter13 "mock 端到端无回归" 结论不可信：mock 每条 MOVE 恒占 2 帧、鲜度恒 −0.05/帧、无天气事件，
致 mock @r48~81 交付，远早于真机均值 469.6 帧。RUSH 前置(r360)/鲜度阈值跨越/任务预算拉紧等
Iter13 关键后期逻辑在 mock 中从未被执行——"无回归"只证明早段未坏，证明不了中后期博弈。

根因（已量化）：`_apply_idle` MOVE 分支 `self.timer = 1` + `_tick_move` 每帧 `timer -= 1`，
每条边恒定 2 帧，完全无视 §2.3.2 的 `到站所需移动量 = ceil(距离×耗时系数)`。用 `samples/map_config.json`
真实边算，最短路 S01→S15 = 424 移动帧 + 20 处理帧 + 6 清障 ≈ 450 帧，叠加天气/任务绕路 → ~470 帧，
与真机 469.6 吻合。

### Changed（仅 `scripts/mock_server.py`，非交付件；client 零改动）
- **移动结算真实化（§2.3.2）**：`build_adjacency` → `build_edges`，边表带 `(distance, routeType, coef)`；
  MOVE 起步按 `math.ceil(distance × coef)` 设 `move_amount`；`_tick_move` 按每帧推进量
  `floor(base × 1000 ÷ weather_mult)` 累计 `move_progress`（替换固定 `timer=1`）。base 按 buff 取
  RUSH_SPEED 1300 / FAST_HORSE 1200 / SHORT_HORSE 1150 / 1000。
- **4 次天气事件（§2.5）**：`WEATHER_SCHEDULE = HOT r100-159 / HEAVY_RAIN r220-279 / MOUNTAIN_FOG r340-399 / HOT r460-519`，
  确定性排期。`WEATHER_MOVE_MULT` 命中水路 1350 / 山路 1100；`WEATHER_FRESH_COEF` HOT×1.5 / RAIN×1.3。
- **鲜度按路线类型（§3.2.2）**：替换恒定 −0.05；移动按 ROAD 0.055 / WATER 0.045 / MOUNTAIN 0.07 / BRANCH 0.065，
  其余状态 0.05；乘天气系数 × 急策系数（RUSH_SPEED×1.25 / RUSH_PROTECT×0.2）。
- **好果转坏阈值（§3.2.1）**：鲜度首次低于 90/80/…/10 各触发 1 篓好果→坏果；`badFruit` 纳入 snapshot
  （此前恒为 0，致使客户端 `break_order_for_verify`/`_plan_attack` 的坏果路径无法被验证）。
- **RUSH r450 强制触发（§6.5）**：`resolve` 中 `rnd >= 450 and not rush` 兜底，不再仅靠 S14 到达触发。
- **默认帧数 250 → 600**。

### Tests
- client 144 项单测全通过（mock 改动不影响 client）。
- mock 端到端（`py scripts/mock_server.py 127.0.0.1 8085 600` + `py main.py 1 127.0.0.1 8085`）：
  **@r459 交付 fresh=74.79 good=97 task=90**，与真机均值 469.6 差 2%；鲜度跨 90/80 阈值并触发好果转坏
  (100→97)，复现真机 7/7 跨 80 场景。RUSH_PROTECT@r439、SCOUT_MARKER_CONSUME@r440(验核 6→3 帧)、
  SQUAD_CLEAR 预清 S13 障碍@r1→r4、SET_GUARD+SQUAD_REINFORCE@r275-276、3 任务 task=90 全路径首次被 mock 执行。

### 仍存差距（次要保真项，按需补全）
蓝方为静态 dummy（进攻设卡/窗口争夺为纯成本无收益）；边按双向可通行（未镜像单向边方向）；
天气按路线类型全图命中（未镜像区域命中）；未实现清障残留通行税/设卡风化/平局冷却等细节。

## [Iteration 13] - 2026-07-04 — 真机归因驱动的策略优化（任务分/鲜度/RUSH 时点）

### 触发
7 场真机对局归因（reports/20260704_corpus.md）：7/7 全部交付（稳定交付硬约束达成），
但胜率仅 3/7（43%），4 场负局分差 1/5/15/35/59 分。丢分集中在三处：
①任务分缺口（对手稳定 180，我方 90~150，单场丢 30~90 分）——`TASK_SEEK_TARGET=90` 把绕路做任务
卡死在 90，慢局机会式任务又被 `_can_afford` 拒；②鲜度崩盘（7/7 跨 90/80 阈值，鲜度 70~81 低于对手
74~89）——关键时刻无冰鉴，根因是领取被 `_can_afford` 拒或被移动竞争挤掉；③交付偏慢（均 469 帧，
RUSH r450 触发时离 S14 远 → r492 才验核，42 帧空隙）拖低用时分并饿死任务预算。

### Changed（策略调参 + 局部逻辑，client/config.py + strategy/decision.py）
- **P1 任务分天花板 90→150**：`TASK_SEEK_TARGET=150`。任务分 1:1 涨至 180（含里程碑跳档），90 以上
  虽用时分饱和但任务分仍净增，旧值 90 等于放弃 1~2 个任务。`_can_afford`+鲜度地板+绕路上限三重守卫仍生效。
- **P2 任务绕路专用更紧安全余量**：新增 `TASK_DETOUR_SAFETY_MARGIN=15`，`_task_detour_target` 用此
  而非通用 25 帧余量（单任务 +30 分 > ~3 帧用时分的潜在损失）。`_can_afford` 加 `safety_margin` 形参，
  默认仍 25（交付/资源/设卡不受影响）。
- **P3 冰鉴领取豁免 + 持有量 2→3**：`CLAIM_ICE_BOX_KEEP=3`；`_maybe_claim` 中冰鉴领取豁免 `_can_afford`
  （2 帧成本 < 1 篓好果转坏的 3.6 分损失）。其余资源仍卡预算。
- **P4 RUSH 前置路由**：新增 `RUSH_PREPOSITION_ROUND=360`，`_plan` 末段在 `round≥360 且未验核` 时
  路由目标临时切为宫门（`_late_route_target`），直奔 S14 不再绕路做任务，确保 RUSH 触发时已就位，
  消除 r450→r492 的验核空隙。已验核则仍奔终点。
- **P5 收紧进攻设卡**：`OFFENSIVE_MIN_OPP_DELAY 12→18`；`_opp_will_pass` 路径不可计算时 fallback
  由"KEY_PASS 保守视为会经过"改为 `False`（不确信则不种），减少 S10 式反噬（1/7）。

### Process
- `logs/README.md`：写入"原始 trace 必须保留"纪律（Iter 12 真机原件被清理导致无法逐帧深挖，后续不删 `.log`）。

### Tests
- 新增 6 项 client 单测（共 144）：任务绕路 150 上限/90 仍绕路、冰鉴领取豁免/马不豁免对照、
  RUSH 前置（早期仍绕路/后期直奔宫门/已验核奔终点）。全 144 项通过；analysis 23 项通过。
- mock 端到端：@r81 交付 fresh=95.95 good=99，无卡死无退赛（mock 仅 3 任务共 90 分，P1 上限由单测覆盖）。

## [Iteration 12] - 2026-07-04 — 日志增厚 + analysis/ 分析模块（真机归因闭环）

### 触发
真实平台对局交付普遍 400+ 帧，远晚于 mock（~81 帧）。当前 trace 日志 `Frame` 行只记录本方，
丢掉对手镜像/节点阻塞/窗口/拒绝码/天气等 inquire 已下发数据，导致真机延迟归因（卡死/绕路/鲜度崩/
进攻反噬/RUSH 过晚）无法可靠复盘——600 帧日志肉眼读不动。Iter 9 "Claude 直接读 trace" 在 mock 下
够用，真机复杂对局不够。本轮两头一起做：①增厚交付件日志；②新建仓库侧 `analysis/` 模块。

### Added（日志增厚：client/main.py + strategy/decision.py）
- `Frame` 行扩展对手镜像 `opp=node|state|fresh|goodFruit|taskScore|verified|delivered`（缺段写 `-`）+ `weather`。
- 新增 `Block` 事件：节点阻塞快照按变化触发（新增/防守值变化/解除各写一行）。
- 新增 `Contest` 事件：本方参与窗口每拍 `contestId/type/ri/myPt/oppPt/myCard/oppCard`。
- 新增 `Reject` 事件：本方被拒动作 `action/target/code`（替代从 events 反推）。
- 新增 `Budget` 事件：交付估值 `est/left`（分析预算漂移）；`decision.py` decide 末尾缓存 `last_deliver_estimate`。
- `Start` 行补记地图角色 `gate/terminals/processNodes`。
- 日志辅助重构为纯函数（`frame_fields`/`block_diff`/`contest_fields`/`reject_fields_list`/`budget_fields`/`start_extra_fields`）便于单测。
- 所有增厚字段对缺失数据降级（mock 蓝方 dummy/无天气/无窗口/恒 accepted 仍能跑），不违反 §10.7 自检。

### Added（分析模块：analysis/，非交付件，纯 stdlib）
- `parser.py`：trace → `MatchTrace`，按 `Startup` 切分会话，旧日志降级兼容。
- `metrics.py`：单场指标（交付/鲜度归因/卡死段/阻塞 encounters/预算漂移/窗口/进攻设卡ROI/RUSH时点/直方图）。
- `diagnose.py`：模式检测 → `Finding`（NO_DELIVER/STALL/FRESHNESS_CRASH/SPOILAGE/BUDGET_DRIFT/EST_OVER_BUDGET/OFFENSIVE_BACKFIRE/RUSH_LATE/REJECT_LOOP/WINDOW_LOSS）。
- `report.py`：Markdown 报告；`corpus.py`：跨场聚合；`cli.py`/`__main__.py`：`python -m analysis`。

### Tests
- `client/tests/test_logger_fields.py` 新增 23 项（对手镜像/Block 变化与解除/Contest/Reject/Budget/Start 地图角色）。
- `analysis/tests/` 新增 23 项（解析器原语/降级/夹具全场/指标/卡死检测），含真实 mock 日志夹具。
- client 单测 **138** 项（115→138）+ analysis 单测 **23** 项，全通过。

### Verified
- 端到端 `py client/main.py` 对 `scripts/mock_server.py`：增厚日志验证——
  `Start` 含 `gate=S14, terminals=[S15], processNodes=[...]`；`Frame` 含 `opp=S01|IDLE|0|0|0|F|F`；
  `Block`：S13 ROCKFALL(r1)→cleared(r5)、S10 己方设卡 def4(r46)→def6(r47 增援)；
  `Budget` 每帧一条；`Contest`/`Reject` mock 下不触发（预期）。**`DELIVER_SUCCESS @r81`** fresh=95.95 good=99 taskScore=90，无退赛/无卡死/无非法。
- 分析端到端 `py -m analysis client/logs/match_mock_match_001_1001.log`：生成报告，正确检出
  `OFFENSIVE_BACKFIRE`（S10 设卡对手未经过，纯成本——即 CLAUDE.md 已记录的 mock 局限），
  鲜度归因（1 篒动作消耗/0 转坏/0 未归因）、RUSH r75→验核 r79→交付 r81、预算漂移 -2，数值与日志一致。

### 待真机回归
取回真机 `client/logs/match_*.log` 后 `py -m analysis <log> --corpus`，重点看：
`STALL`（卡死段位置/时长）、`BUDGET_DRIFT`（估值系统性偏差）、`OFFENSIVE_BACKFIRE`（设卡是否真拖延对手）、
`FRESHNESS_CRASH`（鲜度阈值跨越），据此调 `config` 阈值与策略函数。

## [Iteration 11] - 2026-07-04 — 进攻干扰智能门控 + 小分队增援 + 设卡防卡死兜底 + mock 保真度补全

### 触发
进攻干扰原实现粗糙（`_maybe_set_guard`：仅当前 KEY_PASS、固定 def 4、固定 20 好果门槛、`ENABLE_OFFENSIVE` 全局 flag 默认关、不看对手是否经过、不算时间预算）。
本轮重写为价值判断驱动的智能门控，并默认开启；mock 端到端跑测时发现并修复一个真实卡死回归。

### Changed（进攻设卡：strategy/decision.py `_maybe_set_guard` → `_maybe_offensive_guard`）
- 智能门控（全部满足才种卡，交付优先为硬约束）：
  - 总开关 `OFFENSIVE_ENABLED`(默认开)、非RUSH、未交付；当前节点为 KEY_PASS 且无设卡占用；己方有效设卡 < 2(规则上限)；
  - `_can_afford(SET_GUARD_PROCESS_FRAMES=4)`：种卡不耽误按时交付；
  - 投入后好果 ≥ `OFFENSIVE_GOOD_FRUIT_KEEP`(30)（保交付好果分）；
  - **对手必经此点** `_opp_will_pass`：用对手当前位置到终点的 time_optimal 路径判断，对手已越过则跳过；
  - 预期拖延(forced_pass 时间税, key_pass def4=35帧) ≥ `OFFENSIVE_MIN_OPP_DELAY`(12)；
  - **领先时回避** `_am_leading`+`OFFENSIVE_LEAD_SKIP`：本方总分严格领先则跳过，防给落后对手送破关悬赏(§6.3.3)。
- 新增辅助：`_opp_will_pass`/`_am_leading`/`_own_active_guards`/`_node_max_defense`。

### Changed（小分队增援：strategy/decision.py `_maybe_squad` + `_maybe_reinforce`）
- `_maybe_squad` 优先级：防御性清障/削弱 → **己方设卡增援** → 探路宫门。
- `_maybe_reinforce`：对仍在生效、防守值未顶满的己方设卡 `SQUAD_REINFORCE` +2（不耗好果、不占主车队动作，仅 2 人手），每卡只增援一次省人手；选防守缺口最大者优先。
- `__init__` 新增 `_reinforced_guards` 状态。

### Fixed（设卡防卡死兜底：strategy/decision.py）— 真实败局模式
- **根因**：mock 端到端跑测发现，客户端在 S10(KEY_PASS) 发 `SET_GUARD` 后，mock 不处理该动作→状态仍 IDLE、不生成设卡→客户端下一帧再次触发 `_maybe_offensive_guard`→**反复重发 SET_GUARD 卡死到 TIME_LIMIT（未交付）**。
  这不仅是 mock 问题：**真实服务器若因 OBJECT_BUSY 等拒绝 SET_GUARD，客户端同样会死循环**。
- 修复：新增 `_offensive_guard_node` 状态——种过卡的节点在离开前不再重发（`_update_process_memory` 离开节点时清空）。即使服务端忽略/拒绝 SET_GUARD 也不卡死，离开后仍可在新节点种卡。

### Changed（规则与配置）
- `core/rules.py`：新增 `NODE_MAX_DEFENSE`(normal6/key_pass7/gate4/obstacle_node5) 与 `SET_GUARD_PROCESS_FRAMES=4`。
- `config.py`：移除 `ENABLE_OFFENSIVE`；新增 `OFFENSIVE_ENABLED=True`/`OFFENSIVE_GOOD_FRUIT_KEEP=30`/`OFFENSIVE_EXTRA_GOOD=1`/`OFFENSIVE_MIN_OPP_DELAY=12`/`OFFENSIVE_LEAD_SKIP=True`/`SQUAD_REINFORCE_ENABLED=True`/`SET_GUARD_PROCESS_FRAMES=4`。

### Changed（mock 保真度：scripts/mock_server.py）
- 补全 `SET_GUARD`：4 帧处理→生成己方设卡(def=2+2×extra, 扣好果, ≤2 卡名额, 不在 S15)。
- 补全 `SQUAD_REINFORCE`：对己方设卡 +2 防守至上限（原仅记消耗）。
- `nodes_view` 下发 `guard` 字段（ownerTeamId/defense/active/maxDefense），使客户端 occupied 检查与增援选点可见。
- 新增 `Sim.guards`/`node_type`/`_guard_cap`。

### Tests
- `tests/test_advanced.py`：`world()` helper 增 `score/opp_node/opp_score/opp_delivered` 参数；
  `TestOffensiveGuardFlag`→`TestOffensiveGuard`(5 项：必经且落后→种卡/领先→跳过/对手已越过→跳过/默认关→跳过/好果不足→跳过)；
  新增 `TestSquadReinforce`(2 项：def4<上限→增援/def7=上限→不增援)。
- client 单测 **115** 项全通过（净增 6）。

### Verified
- 端到端 `py client/main.py` 对 `scripts/mock_server.py`：进攻路径完整验证——
  r41 `SET_GUARD@S10`(KEY_PASS) → r45 `GUARD_SET`(good 100→99, def4) → r46 `MOVE`+`SQUAD_REINFORCE`(def4→6) → r47 起正常推进 → **`DELIVER_SUCCESS @r81`** fresh=95.95 good=99 taskScore=90，退出码 0，**无退赛/无非法动作/无卡死**。
- 成本观察：相比 Iteration 10 基线(@r76, fresh96.20, good100)，进攻设卡付出约 4帧+1好果(≈1.8分)；mock 蓝方为静态 dummy 故纯成本无收益（真实对局应由拖延对手~35帧强制通行税收回）。

### 待真机回归
取回 `client/logs/match_*.log`，重点看 `SET_GUARD`/`SQUAD_REINFORCE`/`GUARD_SET` 事件与对手是否真被拖延，据此调 `OFFENSIVE_EXTRA_GOOD`/`OFFENSIVE_MIN_OPP_DELAY`/`OFFENSIVE_LEAD_SKIP`。


## [Iteration 10] - 2026-07-03 — 鲜度结算与窗口争夺强化（反应式出牌 + 阈值冰鉴 + 鲜度路由）

### 触发
平台对局反馈：相对多数队伍**鲜度结算劣势**，且**窗口争夺难赢**。经核任务书 §3.2/§5.4/§6.5 与协议 §7/附录，
定位四类根因并修复。

### Changed（窗口出牌：strategy/decision.py `_window_card` 重写为反应式 3 拍）
- 旧策略每拍按资源优先级出**同一张牌**、不读对手出牌 → 被会反应的对手针对（我方连出 BING → 对方改 XIAN 克 → 2-1 输）。
- 新策略读协议 `roundIndex`/`redPoint`/`bluePoint`/`cards`/`WINDOW_CARD_REVEAL`：第 2/3 拍出**克制对手上一拍的最低成本牌**
  （XIAN→QIANG、BING→XIAN、YAN→XIAN/BING、QIANG→YAN/BING）；无法克制则出同牌求平，再不行弃权省成本。
- **筹码分级**：高筹码(GATE/PASS)才花护卫点(BING)与好果(XIAN)；中筹码(TASK/OBSTACLE)只花好果；低筹码(RESOURCE/DOCK)
  只用马/文书/弃权——不再把全局仅 4 点的护卫点浪费在资源窗口。多窗口选最高筹码者出牌（§5.4.2 每帧仅 1 张）。
- 胜负已定（任一方 2 胜点）即弃权省成本；`_window_played` 同拍去重防重复提交。
- 骑马/疾行令增益时 QIANG_XING 免消耗（§5.4.3），作为反制对手 XIAN 的免费手段。

### Changed（鲜度：冰鉴阈值时机 + 路由鲜度权重 + 绕路鲜度地板）
- 冰鉴 `_freshness_rescue` 由固定 `<78` 改为**阈值感知**：`_track_freshness` 由鲜度跨阈值推断已触发的好果转坏阈值，
  在鲜度距下一个未触发阈值 ≤`ICE_BOX_LEAD` 时提前用冰鉴挡阈值（省 1 好果）；`>ICE_BOX_CAP_AVOID(90)` 不用
  （避免 +10 撞 100 上限浪费且抢破关令验核额度）；酷暑下提前到 `<ICE_BOX_HOT_USE_BELOW`。`CLAIM_ICE_BOX_KEEP` 1→2 多屯以挡多个阈值。
- 路由 `game_map.time_optimal_path` 增 `freshness_weight`：边权 `+= λ×帧数×(路线鲜度损耗−水路损耗)`，差分式（水路不抬高），
  使帧数相近时偏好水路/官道而非山路/支路（§3.2.2）。`_time_path` 传入 `FRESHNESS_ROUTE_LAMBDA`。
- 绕路做任务 `_task_detour_target` 增 `_freshness_allows` 鲜度地板：预计鲜度跌破 `FRESHNESS_DETOUR_FLOOR` 则放弃该绕路。

### Changed（配置 config.py）
- 新增：`ICE_BOX_LEAD=7`、`ICE_BOX_HOT_USE_BELOW=88`、`ICE_BOX_CAP_AVOID=90`、`CLAIM_ICE_BOX_KEEP=2`、
  `FRESHNESS_ROUTE_LAMBDA=5`、`FRESHNESS_DETOUR_FLOOR=65`、`FRESHNESS_LOSS_ASSUME=0.06`、
  `WINDOW_HIGH_STAKES`/`WINDOW_MID_STAKES`、`XIAN_GONG_MIN_GOOD=2`。（初版 λ=3/LEAD=5/FLOOR=60，按"稍微激进"上调。）

### Verified
- client 单测 109 全通过（含新增 5 项反应式窗口测试 + 2 项冰鉴时机测试；旧的"始终 BING"用例改为"高筹码领 BING"）。
- 端到端 `main.py` 对 `mock_server.py`：`DELIVER @r76`，fresh=96.20 good=100 taskScore=90，全程合法心跳无非法动作/退赛。

### 待真机回归
取回 `client/logs/match_*.log`，重点看 `WINDOW_CARD` 胜率与 `FRESHNESS_DROP`/`GOOD_TO_BAD` 事件，据此微调
`ICE_BOX_LEAD`、`FRESHNESS_ROUTE_LAMBDA`、窗口筹码阈值。


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
