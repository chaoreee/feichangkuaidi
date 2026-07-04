# CLAUDE.md — 项目能力基线（Single Source of Truth）

> 本文件是《一骑红尘：荔枝争运战》Agent 交付件开发系统的**唯一能力基线**。
> 所有开发以本文件为依据；每次能力发生变化时**必须同步更新**本文件的"能力矩阵"与"迭代日志"。

- 最后更新：2026-07-04
- 当前轮次：Iteration 31（**beat_top10 P1-A — 分析器数据补全（client trace 富化 + parser 抽取 + aggregator 落盘），纯观测零策略风险**）。落地 `docs/iteration_loop_design.md` P1-A：协议层对手信息几乎全可见（`inquire.players[]` + `over.players[].scoreDetail`），缺口在 client 不记 + parser 不抽。**A. client 富化**（`client/main.py`）：`_log_frame` 补对手字段（`oppBad/oppVerified/oppMoveProg/oppNext/oppGuardAP/oppResources`，零推断）+ 新增 `_log_guards` 设卡变化时记 `Guards` 行（`[node:owner:defense|...]`，对手进攻性设卡唯一可观测源）+ `_log_over` Score 行补 `scoreDetail=[k=v|...]`（双方分项 delivery/tasks/time/goodFruit/freshness/bounty/penalty）；dict 字段序列化为方括号管道列表（`_dict_token`/`_resources_token`）绕开 trace `, ` 切分。**B. parser 抽取**（`analysis/parser.py`）：`_final_score` 去 stub（`_parse_score_detail` 填双方分项，兼容协议 `tasks`/sim `task` 键）；`_on_Guards` 追踪对手设卡区间为 `oppGuards` episodes（附 BREAK_GUARD 响应，旧 trace 回落 BREAK_GUARD 派生）；Frame 扩 opp 字段 → `trajectory.opponent.frames`（稀疏、≤24 条首12末12、短键）+ `freshnessMin`/`badFruitEnd`/`verifyFrame`/`iceUsed`（ICE_BOX 递减推断）+ `tasks.opp.claimed`（oppTask 上跳）。**C. aggregator**（`analysis/aggregator.py`）：`opp_score_components`（与 me 对称，首次量化"对手赢在哪个分项"）+ `opp_guard_stats`（episodes/games/blocked_me_frames）+ `opp_resource_stats`（ice_used/freshness min/end）+ `build_analysis_report` 新增「对手分项与设卡（P1-A）」段。**D. sim 对齐**（`scripts/sim_engine.py`）：`_player_over` 加 `scoreDetail`（键 `task`→`tasks` 对齐协议）。`schemaVersion` 1→2，`CLIENT_VERSION` iter29→iter31。**验收**：352 单测全过（273 client + 61 analysis[42+10 新 `test_parser_opp_fields.py`+4 新 aggregator+5 compact] + 18 sim 零回归）；sim 回灌 report.json 含 opp 分项、`oppGuards`/`frames` 结构正确、`analysis_report.md` 出现 P1-A 段、对账 0 误差；旧 trace 优雅降级（分项 null、oppGuards 回落）。详见 `CHANGELOG.md` §[31]。
- 上一轮次：Iteration 30（beat_top10 P1-B — 精简 trace 派生，纯观测）。更早各轮见 §7 迭代日志。
- **〔Iter 29+ 规划〕真实日志驱动综合迭代优化 P0–P3 蓝图✅定稿**（`docs/iteration_loop_design.md` 详细设计与实现 / `docs/iteration_loop_plan.md` 总览；原"打败前十名"战役，**Iter 32 起泛化为平台综合优化**——前十名为首批高价值样本，**非范围限定**，后续 reports 覆盖平台任意真实对手）。首批证据：10 局对平台前十名真实报告（`reports/`，clientVersion=iter25，N=10 假设级）**4W/6L（40%）**，我方仍是固定点（score 755、deliverFrame 444、freshness 79.9、goodFruit 97、task 150、1 冰鉴）——胜负 100% 由对手鲜度决定（oppFr<80 我 4/4 全胜、oppFr≥82 我 0/5 全负，分隔线 ~82）；负局差距小（L1 −6 / L10 −2 / L9 −16 / L3 −21 / L6 −22）；**1 局灾难性未交付 vs2735（60 分）**——对手进攻性设卡封 S10、我方 `MOVE_BLOCKED_BY_GUARD` 连拒 224 帧未交付。根因定位：`_keep_moving`（decision.py:138-150）重发 `MOVE(next_node_id)` 不检查在途目标被设卡/冷却，MOVING 态短路永不进 `_breakthrough`（与 Iter 8 同源，Iter 8 只修"无在途目标"分支）。**P0–P3 排期**：~~Iter29 **P0** 修设卡卡死~~✅ → ~~Iter30 **P1-B** 精简 trace~~✅（`analysis/compact.py` 从完整 trace 派生事件驱动紧凑格式 ~6–9KB/局落 `reports/`，使我 pull 可直读、绕开"原始 trace 880KB 无法上传"瓶颈；client 零改动）→ ~~Iter31 **P1-A** client trace 富化 + parser 抽取 + aggregator 落盘对手分项分/逐帧轨迹/设卡/资源~~✅ → ~~Iter32 用户取新 reports~~（手动收割已被 codeagent 自动对战取代）→ **Iter32 用 codeagent 跑首轮真实 A/B + analysis 群体归因段**（codeagent 自动收集 `logs/match_*.log` 调 `analysis` 生成 reports，无需 repo 侧契约；群体归因段为对手类分桶）→ **Iter33+ 静态最优**（抬地板 755→770，不读对手，codeagent 真实 A/B）→ **Iter34+ 博弈最优**（对手策略分类器 + 对手类驱动策略切换，替代 mode 拨已封顶 task 绕路的无效杠杆）→ **Iter35+ P3 denial**。**当前 reports 不足以设计 P2/P3**（核心未知"对手凭什么鲜度 88–93"无法回答；分析器缺对手分项分/设卡/资源/逐帧轨迹——协议层全可见、缺口在 client 不记 + parser 不抽）。**新"done"标准（Iter 32 起重定义）**：sim A/B 50 种子**降为回归 + 不变量门**（0 STUCK/对账 0 误差/分段不回归；镜像自博弈 gap 恒 0、mode 恒 EVEN，无法验证博弈层），**真实对战 A/B 升为合入门**（新 vs 老 client 对同一对手池 N≥30 正向才合入）；阈值合入须真实 trace N≥30；验证为负则删（不再累积 variant 平台）。策略须**通用**（读 `start` 动态决策，决赛换新图）。
- **Phase 0 第二批（19 局 iter25）归因✅**（`docs/p0_attribution_batch2.md`）：累计首批 11+本批 19=30 局。**确证并量化**"早交付 vs 质量积累"静态权衡——我方 play 是固定点（总分 755.7±1.81、交付帧 446.6、鲜度 80.4、好果 97、task 150、用 1 冰鉴，跨 19 局近乎常量），胜负 100% 由对手路线决定：oppFr<80 我 9/9 全胜、oppFr≥82 我 1/9 几乎全负（近完美分隔）。`rules.py` 精确重构 19 局 max 误差 0；**真实杠杆证伪"任务"（task_base≥130 双双封顶 delivery 240/task 180，多做任务零分）、确证"鲜度"（+19）+好果（+3，与鲜度耦合）、时间成本仅 -5**——质量路线投影 779 vs 当前 755（+24 上界）。Iter 25 CLAIM_TASK 冷却验证生效（waitingStuck 13→2，~10×）。N=19<30 仍标"假设级"，不合入阈值。
- **Iter 26 Phase B v1 仿真 A/B❌未过门槛**（`docs/calibration_v1.md`）：落地 `strategy/static_planner.py`（鲜度感知路线 + 冰鉴模型 + 终局分投影选择）+ `_ice_detour_target`（就近冰源绕路）+ `--static-planner` sim flag，258 单测过。**但 sim A/B 50 种子未过 §1.2 门槛**：冰鉴优先模式 mean +0.5（fresh 82→92、goodFruit 98→100 兑现，但 task 140→120 回归 −10、交付 +21 帧 −2，单局净 +10、跨种子 mean 仅 +0.5）；任务优先模式冰鉴绕路被抢占→中性零回归。**根因**：分项式绕路下 task 与 ice 争同一 spare-time 预算（零和），+24 上界假设 task 不变被证伪——需全量联合规划器（task bundle+ice+route 一体求解）才能兑现。`ENABLE_STATIC_PLANNER` **保持默认关**，代码保留作 variant 平台。CLIENT_VERSION 不 bump（运行期行为零变化）。
- 进度：**Phase 0✅（两批 30 局）+ Phase A 保真度✅ + Iter 25 投影/修复✅ + Phase B 杠杆确证✅ + Phase B v1/v2/v2+效率门 A/B 均未合入 + beat_top10 P0✅（Iter 29，设卡卡死修复无条件合入）+ P1-B✅（Iter 30，精简 trace 派生，纯观测）+ P1-A✅（Iter 31，分析器数据补全，纯观测）+ P2/P3 规划定稿未实现**。M8 P1-P4 代码全部保留作**工具箱**（race/guard flags 默认关），由 beat_top10 排期驱动逐项评估，不再单列。**前进计划严格按 `docs/iteration_loop_design.md`**（旧 M9 Phase D / calibration_v1 §8 已取代，见 §6）：~~Iter29 **P0** 修设卡卡死~~✅ → ~~Iter30 **P1-B** 精简 trace 回流通道~~✅ → ~~Iter31 **P1-A** 分析器数据补全~~✅ → **Iter32 用 codeagent 跑首轮真实 A/B + analysis 群体归因段**（codeagent 自动收集 `logs/match_*.log` 调 `analysis` 生成 reports，无需 repo 侧契约）→ **Iter33+ 静态最优**（抬地板 755→770，不读对手）→ **Iter34+ 博弈最优**（对手策略分类器 + 对手类驱动策略切换）→ **Iter35+ P3 denial**。新"done"标准：**sim A/B 50 种子降为回归 + 不变量门**（0 STUCK/对账 0 误差/分段不回归；镜像自博弈无法验证博弈层）；**真实对战 A/B 升为合入门**（新 vs 老 client 对同一对手池 N≥30 正向才合入）；阈值合入须真实 trace N≥30；验证为负则删。策略须**通用**（读 `start` 动态决策，决赛换新图）。
- 规则来源：`一骑红尘：荔枝争运战 参赛选手任务书.md`、`一骑红尘：荔枝争运战 通信协议.md`（二者为最高权威，本文件与其冲突时以原始文档为准）

---

## 1. 项目目标与胜负口径

- **目标**：交付一个可提交比赛平台的 Python 客户端（Client），并建立"日志→分析→优化→更新基线"的持续迭代闭环。
- **局内胜负**（任务书 §1.3 / §7）：比赛结束时最终总分高者胜；总分相同直接判平。最终总分 = 送达基础分 + 皇榜任务分 + 用时分 + 好果数量分 + 鲜度品质分 + 破关悬赏分 − 惩罚，最低计 0。
- **平台积分**（任务书 §9）：正常参赛比总分（胜 3 / 负 0）；平分决胜按 鲜度→好果→惩罚 顺序。**未交付则送达/好果/鲜度/用时四项全为 0**，任务分封顶 80、悬赏封顶 25 —— 故"稳定交付"是第一优先。

## 2. 当前系统架构

三层：能力基线（本文件 + docs/）→ 运行期 Client（`client/`，纯 stdlib、可提交、离线可跑）→ 迭代闭环（**分析器驱动**：client 只记 trace 日志 → 仓库侧 `analysis/` 解析多份日志为结构化 Report + 跨局/A/B 聚合报告 → Claude Code 读聚合报告做归因，不再直读 10w 字原始 trace）。
`client/` **本身即提交平台的交付件根目录**：`start.sh` 与 `main.py` 同级，手动打包时 `client/` 的内容直接构成 ZIP 根（不套同名目录）。运行期 client **只记录人类可读 trace 日志**（`client/logs/match_<id>_<pid>.log`），**不含分析模块、不写结构化报告**——对战平台运行时无需实时分析。trace 随交付件下载回本地后复制到仓库 `logs/`（client 之外）供分析。分析模块 `analysis/`（Iter 21 已实现）位于仓库根、**在 client 之外**：`parser.py` 把 trace 解析为 `Report`、`aggregator.py` 跨局聚合，**只抽取事实、不做优化**（Iteration 9 删旧 `analysis/` 后以正确形态回归，详见 `docs/iteration_plan_v2.md`）。数据流与模块协作见 `docs/architecture.md`。
`samples/` 存放参考样例：`map_config.json`（✅ 已提供，中等难度竞技地图原始配置，为 `start` 载荷子集）；`start_message.json`/`inquire_message.json`（⛔ 暂不提供，结构以通信协议 §5/§7 + `docs/protocol.md` 为准）。只读，不被 `client/` import。字段差异详见 `samples/README.md`。

## 3. Agent 职责与工作原则

1. CLAUDE.md 是唯一能力基线（SSOT）。
2. 所有代码实现严格遵循 `docs/delivery_spec.md`。
3. 所有实现严格符合任务书与通信协议。
4. 运行期 trace 日志 + 结构化 `report.json` 写在包内 `client/logs/match_<matchId>_<playerId>.{log,json}`；取回后归档到仓库 `logs/`（client 之外）可追溯。
5. 每轮日志分析：client 只记 trace 日志；仓库侧 `analysis/`（client 之外）`parser` 把取回的 `match_*.log` 解析为结构化 `Report`（事实，纯代码抽取）、`aggregator` 聚合产出跨局/A/B 报告，Claude Code 读聚合报告做归因（**代码抽取事实、AI 只做解释**；分析器不做优化；CLI `python3 -m analysis`）。
6. 每轮优化后同步更新本文件（能力矩阵 + 迭代日志）与 `CHANGELOG.md`。
7. 所有经验/问题/改进沉淀为长期知识，形成闭环。

## 4. 能力矩阵

图例：✅ 已实现　🟡 部分实现　❌ 未实现

### 4.1 通信与协议
| 能力 | 状态 | 备注 |
|---|---|---|
| TCP 长连接（阻塞 socket + 双线程） | ✅ | `communication/tcp_client.py`；接收线程拆帧入队，主线程决策发送 |
| 5 位长度前缀编解码 + 半包/粘包/中文跨包 | ✅ | `protocol/framing.py`；7 项单测通过 |
| 消息 DTO（registration/ready/action + start/inquire/over/error 解析） | ✅ | `protocol/messages.py`、`protocol/actions.py`、`protocol/enums.py` |
| round 对齐（action.round == inquire.round） | ✅ | `main.py` 按 inquire.round 回填 |
| 空动作心跳 + 超时兜底（永不因缺动作退赛） | ✅ | 决策异常/超时降级为 `[]`；端到端验证不退赛 |
| 错误码处理（协议 §11 全量） | ✅ | 立即 error 分类记录；拒绝反馈：PROCESS_REQUIRED 强制处理、移动阻塞类临时拉黑目标绕行(防循环) |

### 4.2 核心状态与规则镜像（core）
| 能力 | 状态 | 备注 |
|---|---|---|
| WorldState 解析（players/nodes/edges/tasks/contests/weather/events） | ✅ | `core/world_state.py`；PlayerView/NodeState 强类型 + 便捷访问；6 项单测 |
| 地图与寻路（Dijkstra，边权=到站移动量/路线距离两种度量） | ✅ | `core/game_map.py`+`core/pathfind.py`；roles 支持 gameplay 或按类型推断；单向边正确；13 项单测 |
| 规则公式镜像（移动/每帧推进/天气/鲜度/时间税/设卡/得分/悬赏） | ✅ | `core/rules.py`；纯函数；15 项单测对齐任务书数值 |

### 4.3 策略（strategy，与通信解耦）
| 能力 | 状态 | 备注 |
|---|---|---|
| 基线推进（最短路→站点处理→宫门验核→交付） | ✅ | `strategy/decision.py`；状态机驱动+处理完成跟踪 |
| 时间感知路由（帧数含固定处理耗时） | ✅ | `game_map.time_optimal_path`；仿真中据此绕开处理站点走山路更快 |
| 资源领取与使用（冰鉴保鲜/马加速/情报探路） | ✅ | 机会式领取+移动中用马；情报(INTEL)探路前方处理点/宫门减时(射程 15，含"可用性"领取守卫) |
| 皇榜任务取舍（机会式 + 预算内绕路）+ 鲜度管理 | ✅ | 目标即当前节点直接做；任务分<90 且预算允许时向近处任务节点绕路；预算守卫计入验核耗时；**Iter 25**：CLAIM_TASK 被 OBJECT_BUSY 拒后 task 级冷却（`_task_cooldown`，6 帧）防重试风暴（真实 trace S10 连停 30+ 帧） |
| 移动/等待中主动续行（防卡死，保交付） | ✅ | `_keep_moving`：MOVING/WAITING 每帧重发 MOVE 到当前在途目标续行（协议允许、不清进度）；**Iter 29（P0）**：重发前校验在途目标是否失效（`_in_transit_target_blocked`：在节点冷却期 **或** 被对手设卡 owner!=我方），失效则丢弃在途目标回落 `_plan` 全量重规划（`_advance` 绕行 / `_breakthrough` FORCED_PASS/BREAK_GUARD）——修复 vs2735 真实败局（对手设卡封 S10、`MOVE_BLOCKED_BY_GUARD` 连拒 224 帧未交付；与 Iter 8 同源，补"在途目标失效"盲区）；无在途目标则重规划。己方设卡不挡己方 |
| 阻塞感知路由（障碍/敌卡绕行） | ✅ | `time_optimal_path(blocked=...)`；仿真中障碍不可绕行时突破 |
| 突破：障碍→T04/CLEAR/强制通行 + 绕行/清障代价权衡 | ✅ | `_breakthrough`；绕行远超就地清障成本时改为清障；保留最低好果 |
| 突破：敌方设卡→攻坚破卡(含破关令)/强制通行 | ✅ | `_plan_attack` 最小投入达防守值，RUSH 绑破关令+3；不够则强制通行；单测覆盖 |
| 窗口出牌（响应本方窗口） | ✅ | `_window_card` 按可支付牌(兵争/献贡/验牒/强行)否则弃权 |
| 终局急策 疾行令/护果令（二选一）+ 破关令 | ✅ | 低鲜度护果令、畅通且远且无马用疾行令、攻坚绑破关令 |
| 小分队探路宫门（减验核 3 帧） | ✅ | `_maybe_squad`；仿真验核 6→3 帧 |
| 防御性小分队：预清路线障碍(SQUAD_CLEAR)/削弱前方敌卡(SQUAD_WEAKEN) | ✅ | 阻塞在路径第 2 跳后由小分队预处理；仿真 SQUAD_CLEAR 提前清障，主车队免耗好果(交付好果 100) |
| 主动设卡(SET_GUARD)/增援等进攻干扰 | 🟡 | 已实现关键关隘设卡逻辑，`config.ENABLE_OFFENSIVE` 默认关闭（delivery-first，占用己方交付时间）；单测覆盖开/关 |
| 博弈投影总线（Layer 1，纯观测） | ✅ | `strategy/projection.py`：每帧投影双方终局分/交付帧→gap→mode(保守/均衡/进取)，带滞后+低置信回落 EVEN；`Projector` 只写 trace、**不改任何动作**（P1 端到端逐帧一致，mock 仍 @r48 交付）；main 每帧输出 `Projection`、切档输出 `ModeChange` |
| 分数质量地板 ΔEV（§3.3，P1.5） | ✅ | `projection.net_score_delta`：纯函数估算增量动作对投影终局分的净影响；供 P2+ 增量动作与 `_can_afford` 组成与门；单测覆盖正/负 ΔEV 与烧好果败局模式。**Iter 25**：鲜度模型从 `AVG_FRESHNESS_LOSS_PER_FRAME=0.06` 平摊升级为路线感知（`freshness_loss_for_path` 逐边 `FRESHNESS_LOSS_MOVE[rt]`×`frames_on_edge` + 处理站/验核停靠 `FRESHNESS_LOSS_BASE`×帧 ×天气系数），ΔEV 调用方（`_detour_net_delta`/绕路/deny/bounty）改逐边路线损耗差——**ΔEV 地板输入首次可信** |
| 档位参数映射（Layer 2，§5.1） | ✅ | `strategy/tuning.py` `tuning_for_mode`：mode→{task_seek_target/detour 上限/ΔEV 阈值/护果令阈值}；EVEN 严格等于既有默认；三档 ΔEV 阈值均非负。**已被决策消费**（见下行） |
| P2 档位调参接入决策（§5.1 行1/2/4 + §3.3 ΔEV 地板） | ✅ | `decision.py` 每帧 `tuning_for_mode(mode)` 刷新参数：`_task_detour_target` 用档位绕路目标/上限并过 ΔEV 地板（`net_score_delta≥阈值`，读任务 `score`）——防 AGGRESSIVE 放宽上限后重演 839cfc9 烧好果败局；`_maybe_rush_protect`/`_rush_speed_warranted` 用档位护果令阈值（AGGRESSIVE 75、余 90）。mock 仍 @r48 交付（EVEN=既有默认）；9 项单测覆盖三档绕路差异/ΔEV 拒低价值/护果令时机 |
| P2 悬赏机会主义（§5.2） | ✅ | `decision.py` `_maybe_bounty`：顺路/近路低代价破对手有效设卡拿破关悬赏——`_plan_attack` 低成本可破 + 额外帧≤`BOUNTY_MAX_EXTRA_FRAMES`(25) + `_can_afford` + `net_score_delta≥BOUNTY_MIN_NET_SCORE`(15，计悬赏得分含+20交付奖−烧好果−耗时/鲜度)。相邻→`BREAK_GUARD`，否则沿绕开其它阻塞的路径靠近；CONSERVATIVE 锁胜/RUSH 保交付时不追。10 项单测覆盖破卡/靠近/高防守·自方卡·远绕路·零收益·已完成跳过 |
| P2 终局交付 race（§5.3） | ✅ | `decision.py` `_endgame_race_state`+`_rush_speed_warranted`：RUSH 相位对手投影将在 `ENDGAME_RACE_WINDOW`(20) 帧内交付且我方也接近时——落后/接近(gap≤0)放宽"远离终点"门槛用 `RUSH_SPEED` 抢交付帧、领先则抑制疾行(留急策护果)；鲜度危急/持马仍不疾行。领先且鲜度临界的 `RUSH_PROTECT` 由既有 `_maybe_rush_protect` 覆盖。非 race 保持原门槛。11 项单测覆盖 |
| P2 窗口 EV / 出牌（§5.4 + §5.1 行5） | ✅ | `decision.py` `_window_card` 重构为代价感知+档位门控：无代价牌(兵争行动点/验牒文书/免费强行 buff——均不影响交付)按克制强度恒出(弱优于弃权)；献贡(烧 1 好果=减交付分)仅非 CONSERVATIVE 且窗口价值明显(`WINDOW_VALUABLE_CONTEST_TYPES`)、好果高于档位下限(`WINDOW_XIANGONG_MIN_GOOD_*`)、鲜度≥80 时出；不为窗口烧马(马留交付提速)；CONSERVATIVE 只出无代价牌/弃权。14 项单测覆盖。（未接入对手出牌倾向预测——需可靠历史与真实 trace，暂缓） |
| P2 突破烧好果意愿（§5.1 行3） | ✅ | `decision.py` `_breakthrough`+`_prefer_forced_pass`：CONSERVATIVE(领先锁好果)且强制通行时间税仍能按时交付(`_forced_pass_tax`+`_can_afford`)时，突破优先 `FORCED_PASS` 不烧好果(障碍与敌卡皆是)；负担不起则回退 CLEAR/BREAK_GUARD 烧好果保交付下限。EVEN/AGGRESSIVE 保持烧好果攻坚(更快)。tuning 增 `protect_good_fruit_on_breakthrough`。10 项单测覆盖。**必要突破前提下只改"方法"不改"是否突破"** |
| P3 对手轨迹 ETA（§6.1，纯观测） | ✅ | `projection.py` `OpponentEta`+`Projector.build_opponent_eta`：估算对手到宫门/终点/任务点/资源点帧数（在途按 `move_progress` 加残余帧、未验核 to_finish 计验核耗时）；置信随终局上升、轨迹频繁变化(原地改目标)打折。`decision.py` 每帧构建存 `self.opponent_eta`、**不改动作**；main 每帧 `Eta` trace。8 项单测覆盖。只作后续 race 的 tie-breaker/争夺判断输入 |
| P3 任务 race（§6.2，默认关） | ✅(默认关) | `decision.py` 两子能力，各带开关：**追平**(`ENABLE_TASK_RACE`)——对手任务分≥`TASK_RACE_OPP_THRESHOLD`(80,逼近90)且我方<90 时 `_task_detour_target` 放宽绕路目标(≥90)/上限(→AGGRESSIVE)，仍过 `_can_afford`+ΔEV 地板；**Deny**(`ENABLE_TASK_DENY`)——`_task_deny_target` 用 §6.1 ETA 抢占对手正奔赴、我方到达帧数≤对手 ETA、且跨对手里程碑(60/90/110)的可领取任务点，过 `_can_afford`+净分≥0+不跑空趟。14 项单测覆盖。默认关，待真实 trace 验证为正后开 |
| P3 鲜度/资源 race（§6.3，默认关） | ✅(默认关) | `decision.py` 两子能力各带开关：**鲜度 race**(`ENABLE_FRESHNESS_RACE`)——对手鲜度比我方高≥`FRESHNESS_RACE_GAP`(处劣势)时 `_freshness_rescue` 把冰鉴使用阈值提到 `ICE_BOX_RACE_USE_BELOW`(88) 提前保阈值；**资源 race**(`ENABLE_RESOURCE_DENY`)——`_maybe_resource_race` 用 §6.1 ETA 抢占对手正争夺、我方到达帧数≤对手 ETA、库存有限的路线附近冰鉴(额外帧≤`RESOURCE_RACE_MAX_EXTRA_FRAMES` 不显著偏离、过 `_can_afford`、未囤够 `RESOURCE_RACE_ICEBOX_KEEP`)。12 项单测覆盖。默认关，待真实 trace 验证后开 |
| P4 条件化 SET_GUARD（§7，默认关） | ✅(默认关) | `decision.py` `_maybe_set_guard` 分发：`ENABLE_CONDITIONAL_GUARD`→`_conditional_guard`（§7.1 六条件：CONSERVATIVE+`gap≥GUARD_MIN_LEAD`、当前节点为关键关隘、对手 ETA∈`(GUARD_SETUP_FRAMES, GUARD_SURVIVAL_WINDOW]`、投入好果后守 `GUARD_KEEP_GOOD_FRUIT`、`_can_afford`、`eta.confidence≥GUARD_MIN_CONFIDENCE`）+ denial 期望分损失 `_guard_denial_value`（对手破卡[受好/坏果≤2 约束]与强制通行取更省者）≥`GUARD_MIN_NET_VALUE`；否则 `ENABLE_OFFENSIVE`→`_basic_set_guard`（M7 基线）。设卡细节写 `guard_decision`，main 每帧 `GuardDecision` trace。15 项单测。默认关，ROI 最低待真实 trace 验证 |
| Phase B 联合静态规划器 v2+效率门（task+ice+route 一体投影 + 每帧效率门，默认关） | 🟡(默认关，A/B 中性) | **Iter 27**（v1 评审后重做）：`strategy/static_planner.py` `project_route` 加 `_path_pickups`（沿途建模 task 领取[贪心到 130 封顶]+ice 收集[+停靠帧鲜度损耗]，路线选择首次能权衡 task-ice 零和）+ `plan_route` 候选集加冰源/任务点 waypoint（含 ice+task 二段组合，读 `start` 拓扑动态生成=通用）+ `_via_path` 拒绝非简单路径（防回溯振荡卡死）。删 v1 `_ice_detour_target`（分项式元凶）；flag-on 跳过 `_task_detour_target`。**Iter 28** 加每帧效率门：`plan_route` 改道门升级为「绝对增益 **与** gain/extra_frames≥`STATIC_PLANNER_MIN_ROUTE_EFFICIENCY`(0.2)」，效率门仅对长绕路(extra≥15帧)生效（吸收投影天气乐观）；`_best_score_for_path` 扩返回 deliver_frame。**sim A/B 50 种子机制验证成功但未过门槛**：mean 747.9 vs 747.8（+0.1 CI[−1.8,+1.9] 中性）、交付帧 +60→+5.5、task 140/140 无回归、分段全一致、0 STUCK（v2 −3.7 双重回归被消除，但 samples 无廉价鲜度→中性非正向）。多图单测证自适应（冰源顺路图改道、偏远图保直送）+ 3 项效率门单测。`ENABLE_STATIC_PLANNER` 默认关，代码保留作通用 variant 平台。26 项单测。详见 `docs/calibration_v1.md` §7-§8 |

### 4.4 日志与分析
| 能力 | 状态 | 备注 |
|---|---|---|
| 人类可读 trace 运行日志（握手/每帧状态/每个动作/错误/结算/异常） | ✅ | `logger/match_logger.py` 输出 `<时钟> <Event> matchId=..., round=..., k=v`；写**包内** `client/logs/match_{matchId}_{playerId}.log`，逐行 flush；事件 Startup/Register/Start/Ready/Frame/Action/Recv/Error/Over/Score/Shutdown。**Iter 25**：Startup `version` 改用 `config.code_version()`（iter 标签+git 短 hash），parser 入 `Report.clientVersion`、index 附 `clientVersion`——解决"log 不记代码版本"使旧/新 client trace 可区分 |
| 高保真自博弈仿真器（Phase A） | ✅ | **Iteration 23 落地 + Iter 24 真实 trace 校准**：`scripts/sim_engine.py` 物理一律调 `core/rules.py`（移动按路线距离×耗时系数、鲜度逐帧损耗+阈值转坏、天气 4 次×60 帧、探路标记 45 帧+处理/验核 -3、RUSH 四条件+450 强制、**路线边空动作 park WAITING**=Iter8 行为、设卡/攻坚/强制通行公式）；`scripts/sim_server.py` 进程内双 `DecisionEngine` 自博弈，复用 `main._log_*` 写 trace 到 `logs/sim/<variant>/match_<seed>_<pid>.log`（matchId=`sim_<variant>_s<seed>` 供聚合器按 seed 配对），CLI `python3 -m scripts.sim_server --games 50 --seeds 1..50 --variant baseline`；`scripts/sim_validator.py` 用 `rules.py` 重算对账 over_data 0 误差。trace 与真实客户端同格式、parser 可读。**Iter 24 校准**（真实 11 局 trace 驱动）：任务池 3 共享×30=90 → 10 沿途站点任务(score 20/pr 3)+**每玩家独立完成追踪**(`completed_by`，双方各达 task 封顶)，TASK_90_REACH 0.04→1.00、交付帧 mean 436.7→455.4(≈真实 456)。**验收**：50 局交付率 1.000、交付帧 452–467(mean 455.4，落真实 [444,492])、0 卡死、对账 0 误差、TASK_90_REACH=1.00。18 项 sim 单测。**残留偏差（假设级）**：freshness sim 136 vs 真实 144、task_base 恒 140(真实 120-150 有方差)、MODE_SWITCHES 0(镜像自博弈→gap 恒 0)、waitingStuck 0(不复现客户端重试 bug)；悬赏/窗口留空、资源不动态刷新、天气区域按路线类型近似待更多 trace |
| 赛后分析 | ✅ | **Iteration 21 分析器驱动落地 + Iteration 22 日志/分析架构重构**（详见 `docs/iteration_plan_v2.md`）。**架构原则**：client trace = 传输格式（单文件 `match_*.log`，抗回传）/ repo 产物 = 分析格式（多文件、可重生成）。client 只记 trace 日志（含 `Rejected`/`CanAffordBlock` 内部信号行 + Start `seed` + WINDOW_CARD `contestType` + **Iter 22 新增**：`Map` 拓扑快照、`Frame` 对手逐帧 `opp*`+`weather`、`Action` 决策时刻 `fresh/goodFruit/gap`、`Bounty` 悬赏快照），**不含分析模块**；仓库根 `analysis/`（client 之外）`parser.parse_log` 把 `match_*.log` 解析为 `Report`（schemaVersion=1，纯 stdlib·永不抛出；Iter 22 修 `weather_hit` 死字段、`decisionTimeline` 去 60 条截断、`USE_RESOURCE` 入 timeline、matchId 占位 `-` 恢复），`aggregator` **累积语料**（跨批次追加）+ 跨局统计 + **场景分段**（交付/未交付、task-90 达成/未达、中局领先/落后、天气/争抢、对手交付 等）+ seed 配对 A/B（95% CI + 分段回归检查 + 低样本标"假设级" N<30/100）+ **运气分类**（expected_win/unlucky_loss/lucky_win/expected_loss，以投影误差作 v1 运气信号）+ 异常局标记 + `rules.py` 对账自检（0 误差，mock 真实分已验）。CLI `python3 -m analysis <dirs>` 产出**多文件**（统一落仓库根 `reports/`，**入库上传**供外部 Claude Code pull 读取）：`reports/match_<id>.report.json`（单局结构化 Report，含 `decisionTimeline`）+ `reports/index.json`（matchId→outcome/score/luckClass/segments/reportPath）+ `reports/analysis_report.md`/`reports/ab_report.md` + `reports/timelines.md`（异常局关键事件链）；source/variant 按路径推断。`logs/**/*.log` gitignore（仅内网采集分析、不上传）。Claude Code 读聚合报告归因，不直读 10w 字 trace。**Iter 30（P1-B）新增精简 trace 派生**：`analysis/compact.py` `compact_trace` 由完整 trace 派生事件驱动紧凑格式（~6–9KB/局，帧状态仅变化时记/动作仅变化时记/连续相同拒绝合并 `REJ x224`/逐帧 Projection·Eta 丢弃只留末帧摘要），`__main__.py` 写 `reports/<matchId>.compact.log`（入库，我 pull 可直读、绕开"原始 trace 880KB 无法上传"瓶颈）+ `--b64`（gzip+base64 ~1.4KB 聊天粘贴）；`parse_compact` 复用 parser helper 还原同 schema Report（roundtrip 关键字段 0 误差）；独立 CLI `python3 -m analysis.compact <file> [--b64]`；spec `docs/compact_trace_format.md`。**Iter 31（P1-A）分析器数据补全**：client `_log_frame` 补对手字段（`oppBad/oppVerified/oppMoveProg/oppNext/oppGuardAP/oppResources`）+ `_log_guards` 设卡变化时记 `Guards` 行 + `_log_over` Score 行补 `scoreDetail=[k=v|...]`（dict 序列化为方括号管道列表）；parser `_final_score` 去 stub（`_parse_score_detail` 填双方分项，兼容 `tasks`/`task` 键）+ `_on_Guards` 追踪对手设卡区间为 `oppGuards` episodes（附 BREAK_GUARD 响应，旧 trace 回落）+ Frame 扩 opp 字段→`trajectory.opponent.frames`（稀疏 ≤24 条）+`freshnessMin`/`badFruitEnd`/`verifyFrame`/`iceUsed`（ICE_BOX 递减推断）+ `tasks.opp.claimed`（oppTask 上跳）；aggregator `opp_score_components`/`opp_guard_stats`/`opp_resource_stats` + `build_analysis_report` 新增「对手分项与设卡（P1-A）」段；sim `_player_over` 加 `scoreDetail`（`task`→`tasks`）。`schemaVersion` 1→2、`CLIENT_VERSION` iter29→iter31。**代码只抽取事实、不做优化**；**单局只作假设来源，决策须基于全语料聚合+CI+分段不回归**（防单点过拟合，对齐 839cfc9 教训）。21 项 parser + 25 项 aggregator + 5 项 compact + 10 项 parser_opp_fields 单测（共 61 analysis + 273 client + 18 sim = 352） |

### 4.5 交付工程
| 能力 | 状态 | 备注 |
|---|---|---|
| start.sh（`./start.sh <playerId> <host> <port>`，可执行） | ✅ | **位于 `client/` 内，与 main.py 同级**（= ZIP 根）；LF、+x（git 100755）、**无中文**，透传参数给同目录 `main.py` |
| 交付件即 `client/` + §10.7 自检 | ✅ | 手动打包：把 `client/` 内容压成 ZIP（start.sh 直接在 ZIP 根，不套同名目录）；**已移除打包脚本**，打包前剔除 `__pycache__/`、`logs/*.log`；对照 §10.7 逐项自查 |
| 纯 stdlib、离线、无现场安装 | ✅ | 零第三方依赖，仅 socket/json/threading/queue/os/time |

## 5. 当前问题与已知限制

- **〔Iteration 21 三问分析认定，最高优先〕验证真空 + 静态层未求解 + 博弈层优先级错置**：① 20 轮/M8 P1-P4 全建在 mock@r48 之上，**Iter 24 前**仓库 `logs/` **零真实对局 trace**；**Iter 24 已破局**——11 局真实平台报告到货（`reports/`，N=11 假设级），坐实 mock@r48 不可信（真实交付 444-492 mean 456），仿真器据此校准（TASK_90_REACH 0.04→1.00、交付帧 mean→455.4）。但 N=11<30，阈值/开关仍不可据此合入，`ENABLE_*` 全默认关、mode 在镜像自博弈里恒 EVEN；② 静态层 `_plan` 是贪心瀑布而非优化求解——**真实证据重定向**：task-90 在真实环境必达（`TASK_90_REACH=1.00`），原"冲 90"杠杆证伪；真实杠杆是"早交付(444-448) vs 延时换质量"的静态权衡（3 局输局皆败于此，见 `docs/p0_attribution.md`）；③ SET_GUARD ROI 最低却占 P4，GATE 验核/deny 收益最高却最弱——**设卡卡死真实证据**（vs2735 `MOVE_BLOCKED_BY_GUARD` 连拒 224 帧未交付）。**前进计划已由 `docs/iteration_loop_design.md`（M10）取代**：旧 Phase D 的 D1（设卡卡死）归入 beat_top10 **P0**、D3（deny）归入 **P3**；D2 窗口预测 / D4 SET_GUARD 暂不做（冻结）。Phase 0→A→B→C 为已落地的历史阶段。阈值/开关合入仍须 N≥30 + 仿真 A/B。
- 无法访问比赛内网运行环境，只能靠导出日志离线分析（任务书 §4 要求）。
- 当前协议不承诺断线重连；连接需稳定，异常需记录，但不强求恢复对局。
- 单帧决策建议 500ms 内完成，策略需轻量并设硬超时降级。
- 地图为变体、局内固定：一切节点/路线/资源/任务候选点/障碍候选点必须从 `start` 动态读取，禁止硬编码（协议附录 A 明确警告）。
- 进攻干扰（主动设卡/增援）默认关闭（`config.ENABLE_OFFENSIVE`）：delivery-first，未验证其对总分的正收益；如需启用需配真实对局数据调参。
- 情报(INTEL)仅在"前方处理点的入边距离≤15"时领取/使用；当前竞技地图各边距离均>15，故该图上情报不生效（属地图特性，非缺陷）。
- 拒绝反馈基于上一帧 actionResults/events；对连续新型阻塞采用"临时拉黑目标+绕行"，不保证在所有极端拓扑下最优，但避免死循环。
- 交付前防卡死依赖"MOVING/WAITING 每帧主动重发 MOVE 到当前目标"（协议允许，MOVE 到当前目标不改道不清进度）。真实服务端在路线边收到空动作会 park 成 WAITING 且不前进——这正是 local-debug-l1 卡死主因（旧实现 MOVING/WAITING 只发空动作从不重规划）。mock 已同步该行为以防回归。
- `TASK_SEEK_TARGET=90` 仅用于限制"为任务绕路"的上限，不再限制机会式(顺路)做任务；拿到更多对局数据后可调。
- **mock 交付帧不代表实战**：`scripts/mock_server.py` 仿真里 ~r48–r55 就交付是简化模型（偏短距离/无天气恶化/无对手争抢/处理打折）的产物；真实平台交付帧基本在 **450 之后**。判断策略（尤其博弈/对抗/终局相关）时一律以实战 ~450+ 为准，禁止拿 mock 帧数当依据。
- **现有安全地板只守时间、不守分数质量**：`_can_afford` 只判断"600 帧内能否交付"，无法阻止"时间够但净分为负"的动作（如为一点任务分绕远烧好果——正是 839cfc9/Iteration 8 的败局模式）。任何"追分"增强都须另加分数质量地板 `ΔEV≥0`（用 `core/rules.py` 估算净收益），详见 `docs/game_theory_projection_strategy.md` §3.3。
- `world.opponent` 已进入投影总线（Layer 1，`strategy/projection.py`）并驱动 **P2 档位调参**（§5.1 行1/2/4）：`decision.py` 每帧按 mode 调节任务绕路目标/上限与护果令阈值，绕路动作过 §3.3 ΔEV 地板。但 mode 前中段因 confidence<0.55 恒为 EVEN（=既有默认），故实战差异主要出现在中后段切档时——须真实 trace 校准 `LEAD_SAFE`/confidence 后才会频繁生效。§5.2 悬赏（`_maybe_bounty`）、§5.3 终局 race（`_endgame_race_state`+race-aware `_rush_speed_warranted`）、§5.4 窗口 EV（`_window_card`）、§5.1 行3 突破烧好果意愿（`_prefer_forced_pass`：CONSERVATIVE 领先时突破优先 FORCED_PASS 保好果）均已接入——**P2 全部完成**。P3 §6.1 对手轨迹 ETA 观测层（`OpponentEta`，每帧 `Eta` trace）、§6.2 任务 race（追平/Deny）、§6.3 鲜度/资源 race（`_losing_freshness_race` 提前用冰鉴、`_maybe_resource_race` 抢冰鉴）均已就绪，全部默认关（`ENABLE_TASK_RACE`/`ENABLE_TASK_DENY`/`ENABLE_FRESHNESS_RACE`/`ENABLE_RESOURCE_DENY`）；Layer 4 §7 条件化 SET_GUARD（`_conditional_guard`：锁胜局在关键关隘按 denial 期望价值设卡，默认关 `ENABLE_CONDITIONAL_GUARD`）亦已实现——**M8 P1-P4 全部落地**。所有 race/guard 均依赖 ETA（对手意图不可观测）、且 P3/P4 增量的胜负收益需真实 trace 校准后逐项打开。SET_GUARD 本身不加分、ROI 最低，仅锁胜且对手无坏果可低价破卡、任务分高时才有 denial 价值。窗口 EV 未做对手出牌倾向预测；ETA 假设对手沿最短路前进（意图不可观测，轨迹变化打折 confidence）；档位切换/ETA 精度均依赖前中段偏低的 confidence（差异主要在中后段），待 P0 真实 trace 校准。
- 投影为观测层近似：**Iter 25 起鲜度模型升级为路线感知**（`freshness_loss_for_path` 逐边 `FRESHNESS_LOSS_MOVE[rt]`×`frames_on_edge` + 处理站/验核停靠 `FRESHNESS_LOSS_BASE`×帧 ×天气系数，替换原 `AVG_FRESHNESS_LOSS_PER_FRAME=0.06` 平摊），ΔEV 地板输入首次可信；悬赏投影两侧同置 0（对称保守）。`LEAD_SAFE=40`/`PROJECTION_MIN_CONFIDENCE=0.55` 等仍为初值，必须用真实 `logs/` trace 校准。对手 confidence 前中段偏低（mode 大概率停在 EVEN）为设计预期，mode 主战场在中后段。

## 6. 后续规划（Roadmap）

M0 文档基线 → M1 通信打通 → M2 核心镜像 → M3 基线策略（稳定交付）→ M4 收益策略 → M5 对抗策略 → M6 分析闭环 → M7 能力补全 → M8 博弈投影层（P1-P4 代码全部落地，待校准）→ M9 分析器驱动证据型迭代（Iter 21–28，Phase 0–C 已落地）→ **M10 真实日志驱动综合迭代优化（Iter 29 起，原"打败前十名"战役，Iter 32 起泛化为平台综合优化；按 `docs/iteration_loop_design.md` P0–P3）**。里程碑详情见 `docs/architecture.md` §Roadmap。

**M8 博弈投影层（P1-P4 代码已实现，全部待校准/默认关）**：把 `world.opponent` 升级为策略一等输入，用"对手投影驱动的风险档位切换 + 分数质量地板"提升胜率与得分上限（详见 `docs/game_theory_projection_strategy.md`）。M8 P1-P4 代码全部保留，但 Iteration 21 triage 后：Layer1/ΔEV/ETA 保留（**ΔEV 输入 Iter 25 鲜度模型升级为路线感知后已可信**）、P2/P3 race 待仿真 A/B 后逐项开关、**P4 SET_GUARD 冻结**。铁律不变：所有增量动作须同时过 `_can_afford`（时间）与 `ΔEV≥0`（分数）；信息不足默认 `EVEN` 保持基线。

**M9 分析器驱动证据型迭代（Iteration 21–28，Phase 0–C 已落地；前进计划已被 M10 beat_top10 取代）**：针对 Iteration 21 三问认定（验证真空 / 静态层未求解 / 博弈层优先级错置），把迭代方式改为证据型闭环 `假设→仿真/trace 证据→实现→A/B→仅当正向才固化`。历史落地顺序：**Iter 21 分析器基础设施** → **Phase 0** 真实 trace 收割 + 归因 → **Phase A** 高保真自博弈仿真器（物理复用 `core/rules.py`）→ **Phase B** 静态规划器（Iter 24 证伪"冲 90"主杠杆后重定义为"交付时机 vs 质量积累"权衡；Iter 26–28 v1/v2/v2+效率门 A/B 均未过门槛，flag 保持关）→ **Phase C** 仿真驱动阈值/开关校准（`calibration_v1.md`）。**原 Phase D（D1 GATE race / D2 窗口预测 / D3 deny / D4 SET_GUARD）不再作为独立前进计划**——D1 归入 beat_top10 P0、D3 归入 P3、D2/D4 暂冻结；详见 `docs/iteration_plan_v2.md` §1.2 的"done"标准。**当前前进计划见 M10**。

**M10 真实日志驱动综合迭代优化（Iteration 29 起；原"打败前十名"战役，Iter 32 起泛化为平台综合优化）**：以"静态最优解 + 博弈最优解"为目标，对**平台真实对手群体**（代表性采样，前十名为首批高价值样本**但不限于**）持续采样、群体归因、A/B 验证、迭代。首批证据：10 局对前十名真实报告（4W/6L、我方固定点 755、胜负由对手鲜度决定、1 局被设卡卡死未交付）。按 P0–P3 推进：**P0**✅ 修设卡卡死 bug（`_keep_moving` 在途目标失效回落 `_plan`，无条件合入）→ **P1-B**✅ 精简 trace 派生（`analysis/compact.py`，落 `reports/` 使 trace 可回流）→ **P1-A**✅ 分析器数据补全（client 富化 + parser 抽对手分项/设卡/资源/轨迹 + aggregator 对手分项段）→ **P2** 鲜度质量积累（抬地板 755→770，P1 归因驱动选分支）→ **P3** denial（设卡/破卡/争抢，真实 trace A/B）。**〔Iter 32 起框架升级〕** codeagent 自动对战闭环取代手动收割；目标"静态最优解基础上追求博弈最优解"——先静态最优（不读对手抬地板），再博弈最优（对手策略分类器 + 对手类驱动策略切换，替代 mode 拨已封顶 task 绕路的无效杠杆）。**验证门重定义**：sim A/B 降为回归 + 不变量门（镜像自博弈无法验证博弈层），真实对战 A/B 升为合入门；flag 默认关、阈值合入须 N≥30、验证为负则删（不再累积 variant 平台）。详见 `docs/iteration_loop_design.md` §0.5。

## 7. 迭代日志（索引）

> **轻量索引**——只记每轮触发与一句能力增量，定位"过去做了什么"。**实现细节（Added/Changed/Tests/Misc）一律见 `CHANGELOG.md` 对应轮次**，本文件不复述，避免双份维护、占用上下文。"现在能做什么"看 §4 能力矩阵，"当前在哪/下一步"看 §5/§6。

| 轮次 | 日期 | 触发 | 能力增量 | 详情 |
|---|---|---|---|---|
| Iter 31 | 2026-07-04 | beat_top10 P1-A（reports 不足设计 P2/P3：对手分项/设卡/资源/轨迹 client 不记+parser 不抽） | **P1-A 分析器数据补全（纯观测，零策略风险）**：client `_log_frame` 补对手字段 + `_log_guards` 设卡行 + `_log_over` scoreDetail（dict 序列化为 `[k=v|...]`）；parser `_final_score` 去 stub + `_on_Guards` opp 设卡 episodes + `trajectory.opponent.frames`（稀疏≤24）+freshnessMin/iceUsed/tasks.opp.claimed；aggregator `opp_score_components`/`opp_guard_stats`/`opp_resource_stats` + P1-A 段；sim `_player_over` 加 scoreDetail（task→tasks）。schemaVersion 1→2、CLIENT_VERSION iter29→iter31。14 项新单测；352 全过；旧 trace 优雅降级 | CHANGELOG §[31] |
| Iter 30 | 2026-07-04 | beat_top10 P1-B（原始 trace 880KB 无法上传，我只能读 reports） | **P1-B 精简 trace 派生（纯观测，client 零改动）**：新增 `analysis/compact.py`（`compact_trace` 事件驱动紧凑格式 ~6–9KB/局 + `parse_compact` 复用 parser helper 还原同 schema Report + `to_b64`/`from_b64`）；`__main__.py` 写 `reports/*.compact.log` + `--b64`；独立 CLI；`docs/compact_trace_format.md` spec。5 项单测；338 全过；sim 50 局每局 ~2.9KB、roundtrip 关键字段 0 误差 | CHANGELOG §[30] |
| Iter 29 | 2026-07-04 | beat_top10 P0（vs2735 设卡卡死 224 帧未交付，4/6 负局含 1 白送未交付） | **P0 设卡卡死修复（无条件合入）**：`_keep_moving` 重发前校验在途目标失效（`_in_transit_target_blocked` 复用 `_is_cooldown`+`active_guard_owner`），失效回落 `_plan`→`_advance`/`_breakthrough`。CLIENT_VERSION iter25→iter29。5 项单测；sim 50 种子 0 回归（镜像自博弈无设卡故路径不触发）。预期 +1 胜 | CHANGELOG §[29] |
| Iter 28 | 2026-07-04 | calibration_v1 §7 下一步①（v2 −3.7 根因：纯绝对增益门放行 +7/+60=0.12/帧 低效长绕路） | Phase B v2+每帧效率门：`plan_route` 改道门加 `gain/extra_frames≥0.2`（仅长绕路 extra≥15 生效），`_best_score_for_path` 扩返回 deliver_frame。3 项效率门单测。**sim A/B 机制验证成功——−3.7→+0.1、交付 +60→+5.5 帧、无 task/分段回归**，但 +0.1 CI 跨 0 中性，samples 无廉价鲜度→flag 保持关 | CHANGELOG §[28] |
| Iter 27 | 2026-07-04 | v1 评审（project_route 冻结 task_base / 候选集过窄 / _ice_detour 分项零和）→ 真正联合求解 | Phase B v2 联合 `static_planner`：`project_route`+`_path_pickups` 沿途建模 task/ice、`plan_route` 候选加 ice/task waypoint（通用）、删 `_ice_detour_target`、`_via_path` 拒非简单路径（修振荡卡死 bug）。多图自适应单测。**sim A/B 仍 −3.7**（投影天气乐观，隐藏信息不可消除）→ flag 保持关 | CHANGELOG §[27] |
| Iter 26 | 2026-07-04 | p0_attribution_batch2 §6 真实杠杆确证（鲜度 +19）→ Phase B 落地 | Phase B v1 `static_planner.py`（鲜度感知路线 + 冰鉴模型 + 终局分投影选择）+ `_ice_detour_target` + sim `--static-planner` flag，258 单测。**sim A/B 50 种子未过门槛**（mean +0.5、task 回归；根因 task-ice 时间零和，分项式无法兑现 +24 上界）→ `ENABLE_STATIC_PLANNER` 保持关，代码保留作 variant 平台，待全量联合规划器 | CHANGELOG §[26] |
| Iter 25 | 2026-07-04 | p0_attribution §6 两个低风险可下手点（N<30 纪律下不涉阈值合入） | CLAIM_TASK 重试修复（OBJECT_BUSY 后 task 级冷却防 S10 重发风暴）+ 鲜度投影升级（0.06 平摊→逐边路线感知 `freshness_loss_for_path`，ΔEV 地板输入首次可信）+ trace 版本戳（`code_version()`，解决 log 不记代码版本）；sim 零回归，302 单测 | CHANGELOG §[25] |
| Iter 24 | 2026-07-04 | 用户上传 11 局真实平台报告 → Phase 0 数据到货 | Phase 0 归因（`docs/p0_attribution.md`）+ 仿真器保真度校准：真实 trace 证伪"冲 90"杠杆（TASK_90_REACH=1.00）、暴露"早交付 vs 质量积累"真实静态权衡 + GATE race 真实证据；sim 任务池改 10 沿途任务+每玩家独立完成→交付帧 mean 455.4≈真实 456、TASK_90_REACH 1.00 | CHANGELOG §[24] |
| Iter 23 | 2026-07-04 | iteration_plan_v2 §5 Phase A——证据型迭代需可复现实验台 | 高保真自博弈仿真器（in-process，物理复用 `rules.py`）：`sim_engine.py` 忠实物理+`sim_validator.py` 对账+`sim_server.py` 双引擎自博弈写同格式 trace。50 局验收交付率 1.000/帧 428–459/0 卡死/对账 0 误差；`TASK_90_REACH=0.04` 暴露 Phase B 杠杆 | CHANGELOG §[23] |
| Iter 22 | 2026-07-04 | trace 事实缺口 / decisionTimeline 不落盘 / 时序受 60 条截断 | 确立「client trace=传输格式（单文件）/ repo 产物=分析格式（多文件）」分离：client 补 Map/对手逐帧/weather/Bounty 事实；analysis 产 `reports/` 多文件（单局 report.json+index+聚合 md+timelines）；logs gitignore、reports 入库。AI 可分层下钻归因 | CHANGELOG §[22] |
| Iter 21 | 2026-07-04 | 策略三问（验证真空 / 静态层未求解 / 博弈层优先级错置） | 落地分析器基础设施（**分析模块移出 client**）：repo 根 `analysis/` 解析 trace→Report→聚合报告（跨局/分段/运气/A-B/对账），client 只记 trace；M8 triage（Layer1/ΔEV/ETA 保留、P2/P3 待 A/B、P4 冻结） | CHANGELOG §[21] |
| Iter 20 | 2026-07-03 | M8 P4 §7 条件化 SET_GUARD——**M8 P1-P4 全部落地** | 主动设卡升级为投影驱动条件开关（锁胜局按 denial 期望价值设卡），默认关 | CHANGELOG §[20] |
| Iter 19 | 2026-07-03 | M8 P3 §6.3 鲜度/资源 race | 鲜度劣势提前保阈值 + 抢占对手争夺的冰鉴，均默认关 | CHANGELOG §[19] |
| Iter 18 | 2026-07-03 | M8 P3 §6.2 任务 race | 任务分落后补差（追平 90）+ 抢占阻断对手里程碑（Deny），均默认关 | CHANGELOG §[18] |
| Iter 17 | 2026-07-03 | M8 P3 §6.1 对手轨迹 ETA | 对手到宫门/终点/任务/资源点帧数估算（纯观测），为 race 铺路 | CHANGELOG §[17] |
| Iter 16 | 2026-07-03 | M8 P2 §5.1 行3 突破烧好果意愿——**P2 全部完成** | CONSERVATIVE 领先时突破优先 FORCED_PASS 保好果，负担不起才回退烧好果 | CHANGELOG §[16] |
| Iter 15 | 2026-07-03 | M8 P2 §5.4 窗口 EV | `_window_card` 重构为代价感知+档位门控，锁住交付好果不被窗口消耗 | CHANGELOG §[15] |
| Iter 14 | 2026-07-03 | M8 P2 §5.3 终局交付 race | 据对手投影分差在"抢交付帧"与"锁交付质量"间取舍 | CHANGELOG §[14] |
| Iter 13 | 2026-07-03 | M8 P2 §5.2 悬赏机会主义 | 顺路低成本破对手设卡拿破关悬赏，受 ΔEV 地板与档位守卫保护 | CHANGELOG §[13] |
| Iter 12 | 2026-07-03 | M8 P2 §5.1 档位调参接入决策 | gap 驱动档位参数正式改动作（绕路目标/护果令阈值），受 ΔEV 地板保护 | CHANGELOG §[12] |
| Iter 11 | 2026-07-03 | M8 P1+P1.5 落地（纯观测） | `world.opponent` 成为投影总线一等输入；ΔEV 地板 + 档位参数基础设施就绪 | CHANGELOG §[11] |
| Iter 10 | 2026-07-03 | 博弈投影层设计评审（未改运行期代码） | 博弈层设计定稿、与历史败局教训对齐；新增 §3.3 ΔEV 地板 | CHANGELOG §[10] |
| Iter 9 | 2026-07-02 | 交付件工程重构（提交格式对齐 + 日志重构） | start.sh 移入 client/=ZIP 根；trace 改人类可读；删旧 analysis/，分析改读 trace | CHANGELOG §[9] |
| Iter 8 | 2026-07-02 | 真实败局 local-debug-l1（卡 S14/WAITING 至 600 帧未交付） | 修正误诊：MOVING/WAITING 主动续行重规划，杜绝交付前卡死 | CHANGELOG §[8] |
| Iter 7 | 2026-07-02 | M7 能力补全 | 错误码处理/拒绝反馈/情报探路/防御性小分队/主动设卡(flag默认关) | CHANGELOG §[7] |
| Iter 6 | 2026-07-02 | M6 分析闭环与打包 | 赛后分析闭环 + 可提交打包（§10.7 自检） | CHANGELOG §[6] |
| Iter 5 | 2026-07-02 | M5 对抗策略 | 阻塞绕行 + 突破(障碍/敌卡) + 窗口出牌 + 终局急策 + 小分队探路减验核 | CHANGELOG §[5] |
| Iter 4 | 2026-07-02 | M4 收益策略 | 时间感知路由 + 机会式任务/资源/冰鉴/马/护果令，过时间预算守卫 | CHANGELOG §[4] |
| Iter 3 | 2026-07-02 | M3 基线策略 | 最短路→处理→验核→交付，可稳定交付得分 | CHANGELOG §[3] |
| Iter 2 | 2026-07-02 | M2 核心镜像 | rules/pathfind/game_map/world_state，状态镜像+规则+寻路可用 | CHANGELOG §[2] |
| Iter 1 | 2026-07-02 | M1 通信打通 | framing/DTO/双线程 TcpClient/logger/main/start.sh，端到端不退赛 | CHANGELOG §[1] |
| Iter 0 | 2026-07-02 | 项目初始化 | CLAUDE.md/docs/CHANGELOG/目录骨架 + IO 模型定案 | CHANGELOG §[0] |
