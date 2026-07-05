# CLAUDE.md — 项目能力基线（Single Source of Truth）

> 本文件是《一骑红尘：荔枝争运战》Agent 交付件开发系统的**唯一能力基线**。
> 所有开发以本文件为依据；每次能力发生变化时**必须同步更新**本文件的"能力矩阵"与"迭代日志"。

- 最后更新：2026-07-05
- 当前轮次：Iteration 21（交付告急估算细化：悲观口径计入途中阻塞真实时间成本）
- 规则来源：`一骑红尘：荔枝争运战 参赛选手任务书.md`、`一骑红尘：荔枝争运战 通信协议.md`（二者为最高权威，本文件与其冲突时以原始文档为准）

---

## 1. 项目目标与胜负口径

- **目标**：交付一个可提交比赛平台的 Python 客户端（Client），并建立"日志→分析→优化→更新基线"的持续迭代闭环。
- **局内胜负**（任务书 §1.3 / §7）：比赛结束时最终总分高者胜；总分相同直接判平。最终总分 = 送达基础分 + 皇榜任务分 + 用时分 + 好果数量分 + 鲜度品质分 + 破关悬赏分 − 惩罚，最低计 0。
- **平台积分**（任务书 §9）：正常参赛比总分（胜 3 / 负 0）；平分决胜按 鲜度→好果→惩罚 顺序。**未交付则送达/好果/鲜度/用时四项全为 0**，任务分封顶 80、悬赏封顶 25 —— 故"稳定交付"是第一优先。

## 2. 当前系统架构

三层：能力基线（本文件 + docs/）→ 运行期 Client（`client/`，纯 stdlib、可提交、离线可跑）→ 迭代闭环（取回 trace 日志由仓库侧 `analysis/` 模块解析归因）。
`client/` **本身即提交平台的交付件根目录**：`start.sh` 与 `main.py` 同级，手动打包时 `client/` 的内容直接构成 ZIP 根（不套同名目录）。运行期 trace 日志写在包内 `client/logs/`，随交付件下载回本地后复制到仓库 `logs/`（client 之外）供 `analysis/` 解析。`analysis/` 是仓库侧分析模块（非交付件、纯 stdlib），把 600 帧 trace 蒸馏成结构化指标 + 归因结论 + Markdown 报告。数据流与模块协作见 `docs/architecture.md`。
`samples/` 存放参考样例：`map_config.json`（✅ 已提供，中等难度竞技地图原始配置，为 `start` 载荷子集）；`start_message.json`/`inquire_message.json`（⛔ 暂不提供，结构以通信协议 §5/§7 + `docs/protocol.md` 为准）。只读，不被 `client/` import。字段差异详见 `samples/README.md`。

## 3. Agent 职责与工作原则

1. CLAUDE.md 是唯一能力基线（SSOT）。
2. 所有代码实现严格遵循 `docs/delivery_spec.md`。
3. 所有实现严格符合任务书与通信协议。
4. 运行期 trace 日志写在包内 `client/logs/match_<matchId>_<playerId>.log`；取回后归档到仓库 `logs/`（client 之外）可追溯。
5. 每轮日志分析由 Claude Code 直接读取 trace 日志产出结论（不依赖 python 分析模块）。
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
| 错误码处理（协议 §11 全量） | ✅ | 立即 error 分类记录；拒绝反馈：PROCESS_REQUIRED 强制处理、移动阻塞类临时拉黑目标绕行(防循环)。**Iter20 全覆盖**：TASK_REQUIREMENT_NOT_MET/TASK_NOT_FOUND→拉黑 taskId 本局不再领取；OBJECT_BUSY(非MOVE)→节点忙冷却；WINDOW_DRAW_RETRY_LIMIT→窗口弃权；INVALID_ACTION_CONFLICT/MOVING_ACTION_FORBIDDEN/RESTING_ACTION_FORBIDDEN→主动作退避 1 帧。`_dedup_actions` 防御性兜底确保每类动作同帧≤1(协议§4.1) |

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
| 资源领取与使用（冰鉴保鲜/马加速/情报探路） | ✅ | 机会式领取+移动中用马；情报(INTEL)探路前方处理点/宫门减时(射程 15，含"可用性"领取守卫)；Iter13 冰鉴领取豁免 `_can_afford`（CLAIM_ICE_BOX_KEEP=3，2帧换3.6分鲜度保障）；**Iter15 冰鉴全面强化**：①使用逻辑鲜度≤90 即用（+10 为交付前永久偏移，线性损耗下无论何时用都+10，前提不撞 100 上限），替换旧"仅近阈值≤7使用"过保守逻辑；②**绕路收集冰鉴**`_ice_box_detour_target`：投影交付鲜度<85 且已持<2 时，绕路去冰鉴节点收集，净鲜度收益(+10−绕路额外损耗)≥6 才绕（排除山路 S06 等高损耗绕路，保留官道 S03→S07），冰鉴节点在 60 帧绕路范围内且时间预算允许。竞技地图实测收 2 个冰鉴(+20 偏移)，鲜度 74.79→90.57、保 80 阈值省 1 篒好果、任务不丢 |
| 皇榜任务取舍（机会式 + 预算内绕路）+ 鲜度管理 | ✅ | **Iter16：取消按模板 ID 硬编码跳过 T04/T06**，改为基于协议模板属性(`processType`/`requiredResourceTypes`/`requiredFreshness`/`score`)动态评估每个任务可做性（地图变化自动适配）。T06(消耗马)持马即做且 `_horse_requiring_task_ahead` 保留马给前方 T06；T04(清障)按 `processType==CLEAR_OBSTACLE` 判定、支持 §5.2 相邻节点处理、突破/机会式/绕路三路径可做(优于 CLEAR：+30 分且不耗好果)。任务分封顶停止条件由 base≥180 改为 `_task_score_capped`(base≥130→180 封顶)，杜绝 130 后无用绕路；`TASK_SEEK_TARGET=130`。机会式做任务用紧余量 15(同绕路口径)。目标即当前节点直接做；任务分未封顶且预算允许时按"分值/额外帧"性价比向近处任务节点绕路；绕路用专用 15 帧安全余量 TASK_DETOUR_SAFETY_MARGIN 释放预算；预算守卫计入验核耗时 |
| 移动/等待中主动续行（防卡死，保交付） | ✅ | `_keep_moving`：MOVING/WAITING 每帧重发 MOVE 到当前目标续行（协议允许、不清进度），无在途目标则重规划——杜绝空动作空等卡死（真实败局：卡在 S14/WAITING 至 600 帧未交付）。**Iter18**：用马加速时同帧并发 `[horse, MOVE(next)]`（不同动作类别不互占额度），杜绝"用马不发 MOVE→被服务端 park 成 WAITING"的卡死复发风险；mock r370 验证同帧处理。**Iter20 修正**：协议§4.1 每帧最多 1 个主车队动作，USE_RESOURCE 与 MOVE 同属主车队动作，`[horse, MOVE]` 非法致 0705 真机 INVALID_ACTION_CONFLICT ×201（mock 恒 accept 未检出）。改回 `[horse]` 单动作（用马本帧不 MOVE，下帧 buff 生效续行，至多 1 帧读条代价），`_dedup_actions` 兜底每类动作同帧≤1 |
| 阻塞感知路由（障碍/敌卡绕行） | ✅ | `time_optimal_path(blocked=...)`；仿真中障碍不可绕行时突破 |
| 突破：障碍→T04/CLEAR/强制通行 + 绕行/清障代价权衡 | ✅ | `_breakthrough`；绕行远超就地清障成本时改为清障；保留最低好果。**Iter20 P3**：`_enter_cost_fn` 对可破敌卡计入好果机会成本（旧版返回 0 致过度偏好破卡）；RUSH 阶段用更紧阈值 `REROUTE_VS_CLEAR_RUSH_EXTRA`(8) 优先就地突破，避免终局绕路超时 |
| 突破：敌方设卡→攻坚破卡(含破关令)/强制通行 | ✅ | `_plan_attack` 最小投入达防守值，RUSH 绑破关令+3；不够则强制通行；单测覆盖。**Iter18**：`_enter_cost_fn`/`_can_break` 路由代价估算同步计入破关令 +3 bonus（新增 `bo_bonus` 形参），与 `_plan_attack` 实际攻坚能力对齐，消除 RUSH 阶段直行代价高估导致的误绕路 |
| 窗口出牌（响应本方窗口） | ✅ | **Iter17 重写 + Iter18 强化**：`_window_card`→`_choose_card` 反应式 3 拍。鲜度<80 时 XIAN 双方不可用、BING 近无敌(唯一克星 XIAN 缺席)→此时 BING 为主牌：能克制则克制、不能则出同牌求平、再不能则出`_strongest_available`(BING>XIAN>QIANG>YAN)争取对手换牌时赢，**绝不弃权白送胜点**(旧逻辑在此场景 0-2 空手输任务窗口)。`_allow_bing` 按筹码分级+预算预留：GATE/PASS(stakes3)`guard>=1`即用；TASK/OBSTACLE(stakes2)`guard>WINDOW_BING_RESERVE(1)`解禁 BING(保留给潜在 GATE/PASS)；RESOURCE/DOCK(stakes1)不花护卫点。`_opp_last_card` cards key 双兼容(颜色/playerId)。**Iter18**：①多窗口优先级 `_contest_priority`(筹码×100+速胜关门+后拍紧迫+deadline 临近)替代纯筹码排序，避免紧迫窗口被弃权；②马匹统一预算 `reserve_horse`(本帧马被加速占用 OR 前方有需马 T06)→ QIANG 不消耗预留马；③反制对手 YAN 改 BING 优先(护卫点机会成本<好果)；④`WINDOW_MIXED_LEAD` 默认关，开启后 R1 按权重混合领出(反剥削 lever)。**Iter19**：`_allow_bing` 低筹码(RESOURCE/DOCK stakes1)guard 充足(`g>WINDOW_BING_LOW_STAKES_RESERVE`=2)时解禁 BING——红方不领过所/官凭、马只 1 匹，stakes1 下旧逻辑只能 ABSTAIN 必输，现 BING(胜 YAN/QIANG、平 BING、仅负 XIAN)是低筹码下唯一能赢/平的牌；保留 2 点给中/高筹码窗口(最多花 2 次 4→3→2)。 |
| 终局急策 疾行令/护果令（二选一）+ 破关令 | ✅ | 低鲜度护果令、畅通且远且无马用疾行令、攻坚绑破关令；Iter13 加 RUSH 前置路由（round≥360 且未验核时直奔宫门，消除 r450→r492 验核空隙） |
| 小分队探路宫门（减验核 3 帧） | ✅ | `_maybe_squad`；仿真验核 6→3 帧 |
| 防御性小分队：预清路线障碍(SQUAD_CLEAR)/削弱前方敌卡(SQUAD_WEAKEN) | ✅ | 阻塞在路径第 2 跳后由小分队预处理；仿真 SQUAD_CLEAR 提前清障，主车队免耗好果(交付好果 100) |
| 主动设卡(SET_GUARD)/增援等进攻干扰 | ✅ | `_maybe_offensive_guard` 智能门控（`config.OFFENSIVE_ENABLED` 默认开）：仅 KEY_PASS+对手必经+`_can_afford(4帧)`+好果预算+预期拖延≥阈值(OFFENSIVE_MIN_OPP_DELAY=18,Iter13 12→18)+领先时回避悬赏；`_opp_will_pass` 路径不可算时 fallback=False（Iter13,不确信不种,减反噬）；种卡后 `SQUAD_REINFORCE` 增援(+2防守,不耗好果)；`_offensive_guard_node` 防服务端忽略/拒绝 SET_GUARD 时反复重发卡死；mock 端到端验证 SET_GUARD→增援→继续推进→交付 |

### 4.4 日志与分析
| 能力 | 状态 | 备注 |
|---|---|---|
| 人类可读 trace 运行日志（握手/每帧状态/每个动作/错误/结算/异常） | ✅ | `logger/match_logger.py` 输出 `<时钟> <Event> matchId=..., round=..., k=v`；写**包内** `client/logs/match_{matchId}_{playerId}.log`，逐行 flush；事件 Startup/Register/Start/Ready/Frame/Action/Recv/Error/Over/Score/Shutdown |
| 日志增厚（对手镜像/阻塞/窗口/拒绝/预算） | ✅ | `main.py` 构造：`Frame` 加 `opp=`+`weather`；新增 `Block`(变化触发)/`Contest`(每拍)/`Reject`(被拒动作)/`Budget`(交付估值 est/left) 事件；`Start` 补 gate/terminals/processNodes。所有字段对缺失降级（mock dummy/无天气/无窗口仍可跑）；纯函数化便于单测 |
| 赛后分析 | ✅ | 仓库侧 `analysis/` 模块（非交付件、纯 stdlib）：`parser`→`metrics`→`diagnose`→`report`/`corpus`；`python -m analysis <log> [--corpus]` 生成 `reports/*.md`。指标对齐真实败局模式（卡死段/鲜度归因/预算漂移/进攻设卡ROI/RUSH时点），诊断 Finding 映射到 config/策略改动点 |

### 4.5 交付工程
| 能力 | 状态 | 备注 |
|---|---|---|
| start.sh（`./start.sh <playerId> <host> <port>`，可执行） | ✅ | **位于 `client/` 内，与 main.py 同级**（= ZIP 根）；LF、+x（git 100755）、**无中文**，透传参数给同目录 `main.py` |
| 交付件即 `client/` + §10.7 自检 | ✅ | 手动打包：把 `client/` 内容压成 ZIP（start.sh 直接在 ZIP 根，不套同名目录）；**已移除打包脚本**，打包前剔除 `__pycache__/`、`logs/*.log`；对照 §10.7 逐项自查 |
| 纯 stdlib、离线、无现场安装 | ✅ | 零第三方依赖，仅 socket/json/threading/queue/os/time |

## 5. 当前问题与已知限制

- 无法访问比赛内网运行环境，只能靠导出日志离线分析（任务书 §4 要求）。真机日志取回后 `python -m analysis <log> [--corpus]` 生成 `reports/*.md`，由 Claude 读报告驱动迭代。
- 当前协议不承诺断线重连；连接需稳定，异常需记录，但不强求恢复对局。
- 单帧决策建议 500ms 内完成，策略需轻量并设硬超时降级。
- 地图为变体、局内固定：一切节点/路线/资源/任务候选点/障碍候选点必须从 `start` 动态读取，禁止硬编码（协议附录 A 明确警告）。
- 进攻干扰（智能设卡）默认开启（`config.OFFENSIVE_ENABLED`）：仅在对手必经 KEY_PASS 且自身预算充足、未领先时种卡（4帧+1好果成本换对手~35帧强制通行税）。Iter13 收紧：`OFFENSIVE_MIN_OPP_DELAY 12→18`、`_opp_will_pass` 路径不可算时 fallback=False（不确信不种），减少真机 S10 式反噬（1/7）。mock 中蓝方为静态 dummy，故进攻设卡为纯成本无收益（真实对局应由拖延对手收回）。`OFFENSIVE_LEAD_SKIP` 领先时回避以防空悬赏反噬。真实对局正收益待回归验证，可按数据调 `OFFENSIVE_EXTRA_GOOD`/`OFFENSIVE_MIN_OPP_DELAY`。
- 情报(INTEL)仅在"前方处理点的入边距离≤15"时领取/使用；当前竞技地图各边距离均>15，故该图上情报不生效（属地图特性，非缺陷）。
- 拒绝反馈基于上一帧 actionResults/events；对连续新型阻塞采用"临时拉黑目标+绕行"，不保证在所有极端拓扑下最优，但避免死循环。
- 交付前防卡死依赖"MOVING/WAITING 每帧主动重发 MOVE 到当前目标"（协议允许，MOVE 到当前目标不改道不清进度）。真实服务端在路线边收到空动作会 park 成 WAITING 且不前进——这正是 local-debug-l1 卡死主因（旧实现 MOVING/WAITING 只发空动作从不重规划）。mock 已同步该行为以防回归。
- `TASK_SEEK_TARGET=130`（Iter16 由 180 下调至封顶点）= 任务分 180 对应的基础分上限（base≥130+里程碑50=180 封顶）。超过 130 的任务零分收益（任务分已 180、送达基础分 base≥90 饱和、用时分 base≥90 饱和），只徒增用时与鲜度损耗。`_task_detour_target` 与 `_maybe_task` 均以 `_task_score_capped`(base≥130) 为停止条件。配套 `TASK_DETOUR_SAFETY_MARGIN=15`（绕路与机会式做任务共用紧余量，区别于通用 25）与 `FRESHNESS_DETOUR_FLOOR=65`/`TASK_DETOUR_MAX_EXTRA_FRAMES=70` 守卫不致鲜度崩盘/超时。真机回归后若出现为任务险些超时或鲜度跌破 70，回退到 120。
- **任务模板不再硬编码跳过**（Iter16）：旧 `SKIP_TASK_TEMPLATES=("T04","T06")` 按 ID 跳过导致 5 模板地图最多 3 任务(base90→任务分 125)，结构性到不了 180。现改为基于协议模板属性(`processType`/`requiredResourceTypes`/`requiredFreshness`/`score`)动态评估：T06 持马即做且 `_horse_requiring_task_ahead` 保留马给前方 T06；T04 按 `processType==CLEAR_OBSTACLE` 判定、支持 §5.2 相邻节点处理。地图变化时自动适配，无需改代码。真机回归若 T06 消耗马导致用时分下降过多，可加"保留 1 匹马用于加速"的二次守卫。
- **冰鉴绕路收集**（Iter15）：竞技地图冰鉴在 S03/S06/S07（§3.3），最短路 S01→S02→S04→S05→S09→… 不经过。`_ice_box_detour_target` 在投影交付鲜度<85 时绕路收集：净鲜度收益(+10−绕路额外损耗)≥`ICE_BOX_DETOUR_NET_MIN`(6) 才绕——排除山路绕路（S06：S01→S06 山路 0.07，净收益<6），保留官道绕路（S02→S03→S07→S09，ROAD 0.055，净收益~7，且下游任务节点 S09 等不丢）。mock 实测收 2 个冰鉴(+20 偏移)，鲜度 74.79→90.57、good 97→98（保 80 阈值省 1 篒好果）、task 90 不变、交付 r459→r482（+23 帧换 +28 鲜度分+1.8 好果分−2.7 用时分 ≈ +27 净分）。已持冰鉴≥`ICE_BOX_DETOUR_KEEP`(2) 或投影≥85 时停止绕路（鲜度充足不牺牲用时分）。受 `ICE_BOX_DETOUR_MAX_EXTRA_FRAMES`(60)、`_can_afford`(25 帧余量)守卫不致超时。
- **任务分卡 150 根因**（Iter15）：4/7 场任务分恰为 150（旧 TASK_SEEK_TARGET 上限），非预算/路线限制——对手稳定 180 证明可达。Iter15 上限提至 180 后，pre-r360 窗口内可继续绕路做任务至 180；但 `RUSH_PREPOSITION_ROUND=360` 仍在此帧后切宫门目标（保 r450→r492 验核空隙修复），故 180 的实现依赖 r360 前任务节点密度。2 场任务分 90 的负局（120521/120605）为路线任务节点稀疏（仅 3 个在途），非上限所致，提升上限不改变。
- **窗口出牌策略**（Iter17 修正 + Iter18 强化）：旧 `_window_card` 在鲜度<80（真机常态）+ 中筹码(TASK/OBSTACLE) 场景结构性必输——`allow_bing=stakes>=3` 禁 BING、`allow_xian` 要 fresh>=80 → 只能 ABSTAIN → 0-2 输、丢 30 分任务分；且"无法克制即弃权"在鲜度<80 时错误（BING 近无敌应继续出）。Iter17 改为：`_allow_bing` 按筹码分级+预留(GATE/PASS 尽情花、TASK/OBSTACLE `guard>WINDOW_BING_RESERVE(1)` 解禁、RESOURCE/DOCK 不花)；`_choose_card` 无法克制时出同牌求平或最强可用牌、不弃权。护卫点 4 点不恢复、唯一用途=BING，预算紧张：真机回归后若中筹码耗尽导致后续 GATE 窗口无 BING，上调 `WINDOW_BING_RESERVE`(1→2)。**Iter18 强化**：①多窗口同帧只出 1 张(§5.4.2)时改用 `_contest_priority`(筹码×100+速胜关门+后拍紧迫+deadline)排序，避免紧迫窗口被高筹码窗口挤掉弃权；②马匹统一预算 `reserve_horse`：本帧马被加速占用 OR 前方有需马 T06(+30 分)时 QIANG 不消耗马(已有 buff 免消耗除外)；③反制对手 YAN 改 BING 优先(护卫点机会成本<好果)。反 exploitation 混合出牌已实现为 `config.WINDOW_MIXED_LEAD` lever（默认关，开启后 R1 按权重 BING0.5/XIAN0.25/QIANG0.15/YAN0.10 混合，roll 由 contestId+roundIndex+round+playerId 哈希得、确定性可复现）——确定性出牌在鲜度≥80 仍可被反应式对手针对。**Iter18 已补全 mock 窗口争夺仿真**（RESOURCE+TASK，见 §5 mock 保真度），端到端验证红方反应式出牌链路（领出/反制/成本/揭示读取/胜负授予）跑通；但 mock 蓝方刻意偏弱（BING 试一拍即弃权），未模拟强对手 exploitation，故 `WINDOW_MIXED_LEAD` 仍待强对手压测后再默认开启。**Iter19 已补低筹码窗口出牌能力**：旧 `_allow_bing` 对 stakes1 一律 False，红方在 RESOURCE/DOCK 窗口不领过所/官凭、马只 1 匹 → 只能 ABSTAIN 必输；现 guard 充足(`g>WINDOW_BING_LOW_STAKES_RESERVE`=2)时解禁 BING（胜 YAN/QIANG、平 BING、仅负 XIAN），mock 端到端 S03 ICE_BOX 窗口 1-0 胜（BING 领出→BING 胜弃权→ABSTAIN 平）。保留 2 点给中/高筹码窗口，最多花 2 次。真机回归后若低筹码耗光 guard 致 GATE 窗口无 BING，上调 `WINDOW_BING_LOW_STAKES_RESERVE`(2→3)。
- **mock 保真度**（Iter14 对齐 / Iter18 补窗口 / Iter20 补拒绝码）：`scripts/mock_server.py` 为开发工具（非交付件）。Iter14 前每条 MOVE 恒占 2 帧、鲜度恒 −0.05/帧、无天气，致 mock @r48~81 交付，远早于真机 469.6 均值，无法验证 RUSH 前置(r360)/鲜度阈值/任务预算等后期逻辑。Iter14 按 §2.3.2/§2.5/§3.2 真实化：MOVE 按 `ceil(距离×耗时系数)` 累计推进、4 次天气确定性排期(HOT/HEAVY_RAIN/MOUNTAIN_FOG/HOT)、鲜度按路线类型×天气系数×急策系数、跨 90/80/…/10 阈值触发好果转坏、RUSH r450 强制触发、默认 600 帧。mock 端到端 @r459 交付 fresh=74.79 good=97（跨 80 阈值），与真机均值差 2%。**Iter18 补全窗口争夺仿真**：3 拍流程 + WINDOW_CONTEST_START/WINDOW_CARD_REVEAL/WINDOW_CONTEST_END 事件 + cards 字段(颜色 key) + 牌成本扣减(护卫点/好果/马/过所) + 胜负授予(RESOURCE/TASK)。触发点 `WINDOW_TRIGGERS={("S03","CLAIM_RESOURCE","ICE_BOX"),("S11","CLAIM_TASK","TK2")}`（Iter19 加 RESOURCE 触发：低筹码 BING 解禁后红方在 RESOURCE 窗口也能出牌）。蓝方虚拟资源池出牌(刻意偏弱：BING 试一拍即弃权，保交付稳定)。mock 端到端验证：S03 RESOURCE 窗口 1-0 胜(BING 领出平→BING 胜弃权→ABSTAIN 平，获 ICE_BOX)、S11 TASK 窗口 2-0 胜(BING→XIAN 反制→XIAN)，交付@r498 fresh=89.30 good=96 task=150。**Iter20 关键教训 + 拒绝码仿真**：mock 旧版恒 `accepted=True`（`build_inquire` 硬编码），致 Iter18 `[horse, MOVE]` 非法并发（协议§4.1 每帧≤1 主车队动作）从未被 mock 检出，真机 0705 爆发 INVALID_ACTION_CONFLICT ×201。Iter20 补拒绝码仿真：`_validate_actions` 按码校验，`build_inquire` 发 `accepted=False`+`errorCode` 的 actionResults。常开 `INVALID_ACTION_CONFLICT`（>1 主车队动作，回归守卫）；env 注入 `MOCK_REJECT_TASK=<taskId>`→`TASK_REQUIREMENT_NOT_MET`、`MOCK_REJECT_RESOURCE=<nodeId>:<type>`→`OBJECT_BUSY`。端到端验证 P0 断环：`MOCK_REJECT_TASK=TK2` 仅 1 次拒绝（非 142）、交付@r491 task=120（TK2 被弃）；`MOCK_REJECT_RESOURCE=S03:ICE_BOX` 仅 1 次拒绝（非 130）、交付@r495；默认运行 0 拒绝（P1 dedup 生效，每帧≤1 主车队动作）。**仍存差距**：蓝方为静态 dummy（进攻设卡为纯成本无收益；窗口争夺蓝方刻意偏弱不模拟强对手）；边按双向可通行（未镜像单向边方向）；天气按路线类型全图命中（未镜像区域命中）；未实现清障残留通行税/设卡风化/平局冷却/GATE/PASS 窗口/WINDOW_DRAW_RETRY_LIMIT 等细节。这些为次要保真项，按需补全。

## 6. 后续规划（Roadmap）

M0 文档基线（本轮，✅ 交付中）→ M1 通信打通 → M2 核心镜像 → M3 基线策略（稳定交付）→ M4 收益策略 → M5 对抗策略 → M6 分析闭环 → M7+ 按真实日志迭代。里程碑详情见 `docs/architecture.md` §Roadmap。

## 7. 迭代日志

| 轮次 | 日期 | 触发 | 主要改动 | 能力增量 | 关联 |
|---|---|---|---|---|---|
| Iteration 21 | 2026-07-05 | `_delivery_panicking` 估算审查：乐观口径忽略途中阻塞，密集障碍/敌卡下低估交付时间、迟触发告急 | 交付告急估算细化（悲观口径）：新增 `_enter_cost_real_frames`（交付时间专用真实帧回调，区别于 `_enter_cost_fn` 的好果机会成本折算——可破敌卡按 0 帧计 §6.3.1 攻坚无额外处理帧、不可破敌卡按强制通行时间税 §6.3.2、障碍清障 6/强制通行 8）；新增 `_deliver_estimate_pessimistic` 取"绕行 path_b（屏蔽阻塞）"与"直行含税 path_t"较小者，与 `_advance` 实际"绕行 vs 突破"决策口径一致，两者皆不可达→必然超时告急；`_delivery_panicking` 改用悲观估算。`_can_afford` 等预算门控仍用乐观估算（由 `DELIVER_TIME_SAFETY_MARGIN` 吸收偏差），口径分离避免连锁改动。新增 4 项单测（共 170）全通过 | 告急判定从"乐观忽略阻塞"升级为"悲观计入真实阻塞成本"：前方连续障碍/不可破敌卡时提前触发保交付模式，消除"已来不及却仍在绕路做任务"风险；可破敌卡不虚假抬高估算（攻坚仅耗好果不耗时间），避免误告急放弃正当绕路 | `CHANGELOG.md` |
| Iteration 20 | 2026-07-05 | 0705 真机 37 场回退（交付 20/37、REJECT_LOOP 37/37、17 场未交付） | 三类根因修复 + 受卡代价优化：**P1**协议§4.1 每帧≤1 主车队动作，`_keep_moving` 用马改回 `[horse]` 单动作（Iter18 `[horse,MOVE]` 非法致 INVALID_ACTION_CONFLICT ×201），`_dedup_actions` 兜底每类动作同帧≤1；**P0**`_apply_rejection_feedback` 全覆盖——TASK_REQUIREMENT_NOT_MET/TASK_NOT_FOUND→拉黑 taskId、OBJECT_BUSY(非MOVE)→节点忙冷却、WINDOW_DRAW_RETRY_LIMIT→窗口弃权、INVALID_ACTION_CONFLICT/MOVING_ACTION_FORBIDDEN/RESTING_ACTION_FORBIDDEN→主动作退避，各收益路径消费黑名单；**P2**`_delivery_panicking` 交付告急时禁绕路/未验核先去宫门/窗口弃权；**P3**`_enter_cost_fn` 可破敌卡计入好果机会成本（`_break_good_needed`×`BREAK_GUARD_GOOD_FRAME_EQ`，旧版返回 0 过度偏好破卡）、RUSH 阶段更紧阈值 `REROUTE_VS_CLEAR_RUSH_EXTRA`(8) 优先就地突破、RUSH 禁一切绕路。新增 10 项单测（共 167）全通过；mock 端到端交付@r498 无回归 | 消除 0705 三大回退根因：拒绝循环(37/37)、非法并发(201冲突)、预算告急不保交付(35/37)；受卡破卡代价评估修正。预期交付率回升至 100%、任务分回升 | `CHANGELOG.md` |
| Iteration 0 | 2026-07-02 | 项目初始化 | 建立项目基线文档、docs/（architecture/delivery_spec/protocol/task）、CHANGELOG、目录骨架；确定 IO 模型=阻塞 socket+双线程 | 文档基线成型 | `CHANGELOG.md` |
| Iteration 1 | 2026-07-02 | M1 通信打通 | 实现 framing/enums/messages/actions、双线程 TcpClient、JSONL logger、占位 DecisionEngine、config、main 启动闭环、start.sh、mock_server、framing 单测；端到端跑通 registration→over，全程空动作心跳不退赛 | 通信层可用 | `CHANGELOG.md` |
| Iteration 2 | 2026-07-02 | M2 核心镜像 | 实现 core：rules(规则公式镜像)、pathfind(Dijkstra)、game_map(GameMap 解析+寻路)、world_state(WorldState 每帧解析)；main/decision 接线为每帧构建 WorldState 传入 decide；新增 40 项单测全通过；mock 端到端回归通过 | 状态镜像+规则+寻路可用，M3 策略就绪 | `CHANGELOG.md` |
| Iteration 3 | 2026-07-02 | M3 基线策略 | `decide` 实现最短路推进→固定处理→宫门验核(RUSH)→交付；GameMap 增 process_nodes 解析；mock_server 升级为加载 map_config 的全流程仿真；新增 10 项策略单测(共 50)全通过；仿真跑通 @r60 交付成功(鲜度97/好果100) | 可稳定交付得分 | `CHANGELOG.md` |
| Iteration 4 | 2026-07-02 | M4 收益策略 | 时间感知路由(time_optimal_path 计入处理耗时)；机会式皇榜任务/资源领取/冰鉴保鲜/马加速/护果令，均过时间预算守卫；mock 扩展支持资源/任务/急策/buff；新增 17 项单测(共 67)全通过；仿真 @r51 交付(更早)+任务分60+领取用马 | 收益策略可用，交付更早更优 | `CHANGELOG.md` |
| Iteration 5 | 2026-07-02 | M5 对抗策略 | 阻塞感知路由(绕行)+突破(障碍 T04/CLEAR/强制通行、敌卡攻坚含破关令/强制通行)、窗口出牌、疾行令/护果令二选一、小分队探路宫门减验核；mock 加障碍/清障/小分队探路/验核减时；新增 14 项单测(共 81)全通过；仿真障碍突破CLEAR+探路使验核6→3帧+交付@r55(鲜97.25/任务60) | 遇阻能突破，具备对抗动作 | `CHANGELOG.md` |
| Iteration 6 | 2026-07-02 | M6 分析闭环与打包 | main 增每帧 frame 记录并修复 over 摘要丢字段的日志 bug；analysis/ 四件套(parser/evaluator/optimizer/report)+CLI，真实日志产出 analysis.md；scripts/build_zip.py 打包提交 ZIP 并执行 §10.7 自检(全 PASS)；新增 5 项分析单测(共 86)全通过 | 具备赛后分析闭环与可提交打包 | `CHANGELOG.md` |
| Iteration 7 | 2026-07-02 | M7 能力补全 | 错误码分类+拒绝反馈(PROCESS_REQUIRED强制处理/移动阻塞拉黑绕行)；情报探路减时(含可用性领取守卫)；绕行vs清障权衡；预算内绕路做任务；防御性小分队清障/削弱；主动设卡(flag默认关)；新增 10 项单测(共 91 client+5 analysis)全通过；仿真 SQUAD_CLEAR 预清障使交付好果保 100、@r48 交付 | 补齐部分/未实现能力，鲁棒性与得分提升 | `CHANGELOG.md` |
| Iteration 8 | 2026-07-02 | 真实败局 local-debug-l1（未交付、卡在 S14/WAITING 至 600 帧）驱动 | **修正误诊**（非超时）：根因为 MOVING/WAITING 被动发空动作从不重规划→交付前空等卡死。改 `_keep_moving` 主动续行(重发 MOVE 到目标；无在途目标则重规划)；回退误诊的交付冲刺+任务上限；mock 改为"路线边空动作被 park 成 WAITING"以复现并验证；analyzer 增卡死诊断；101 项单测通过，端到端不再卡死、@r48 交付 | 杜绝交付前任何位置卡死，保证交付 | `CHANGELOG.md` |
| Iteration 9 | 2026-07-02 | 交付件工程重构（提交格式对齐 + 日志重构） | ①`start.sh` 移入 `client/`（与 main.py 同级 = ZIP 根），删除中文注释，指向同目录 `main.py`，git 100755；`client/` 即交付件根目录。②`MatchLogger` 改为人类可读 trace（`<时钟> <Event> matchId=..., round=..., k=v`），日志落**包内** `client/logs/`（`resolve_log_dir` 改指 client 目录）；main 全量改用语义化 `trace()`（Startup/Register/Start/Ready/Frame/Action/Recv/Error/Over/Score/Shutdown），空动作显式记 `action=NONE`，仅超预算附 `ms`。③删除 `analysis/` 模块与 `scripts/build_zip.*`、`dist/`；分析改由 Claude Code 直接读 trace。④新增仓库 `logs/`（client 之外）为采集/分析目录 + README；`.gitignore` 改忽略 `client/logs/*.log`。⑤刷新基线文档/README/architecture/delivery_spec。96 项 client 单测通过，mock 端到端 @r48 交付、trace 日志格式正确 | 交付件可直接手动打包提交；日志精简可读、随包取回即分析 | `CHANGELOG.md` |
| Iteration 10 | 2026-07-03 | 鲜度结算与窗口争夺强化（反应式出牌 + 阈值冰鉴 + 鲜度路由） | `_window_card` 重写为反应式 3 拍（读对手上一拍牌出最低成本克制牌，胜负已定弃权）；冰鉴 `_freshness_rescue` 阈值感知（跨阈值推断+提前挡阈值）；路由 `freshness_weight` 差分式偏好水路/官道；绕路鲜度地板。109 项单测通过，mock @r76 交付 fresh=96.20 good=100 task=90 | 鲜度/窗口博弈强化 | `CHANGELOG.md` |
| Iteration 11 | 2026-07-04 | 进攻干扰智能门控 + 小分队增援 + 设卡防卡死兜底 + mock 保真度补全 | ①`_maybe_set_guard`→`_maybe_offensive_guard` 智能门控（`OFFENSIVE_ENABLED` 默认开）：KEY_PASS+对手必经(`_opp_will_pass`)+`_can_afford(4帧)`+好果预算+预期拖延≥阈值+领先时回避悬赏(`_am_leading`)。②`SQUAD_REINFORCE` 增援己方设卡(+2防守,不耗好果,每卡一次)。③`rules.NODE_MAX_DEFENSE`/`SET_GUARD_PROCESS_FRAMES`。④**防卡死兜底**`_offensive_guard_node`：种过卡的节点离开前不再重发（真实败局模式：服务端忽略/拒绝 SET_GUARD 时反复重发卡死，mock 端到端复现并验证修复）。⑤mock 补全 SET_GUARD(4帧处理→生成设卡/扣好果/≤2卡名额)+SQUAD_REINFORCE(+2至上限)+nodes_view 下发 guard。115 项单测通过，mock 端到端 SET_GUARD@S10→增援 def4→6→@r81 交付 fresh=95.95 good=99 task=90，无退赛/无卡死 | 进攻干扰可用且不卡死；mock 可验证设卡/增援路径 | `CHANGELOG.md` |
| Iteration 12 | 2026-07-04 | 日志增厚 + analysis/ 分析模块（真机归因闭环） | 真机交付普遍 400+ 帧、trace 只记本方导致无法归因。①**日志增厚**（`main.py`）：`Frame` 加对手镜像 `opp=`+`weather`；新增 `Block`(变化触发)/`Contest`(每拍)/`Reject`(被拒动作)/`Budget`(交付估值) 事件；`Start` 补 gate/terminals/processNodes；`decision.py` 暴露 `last_deliver_estimate`；纯函数化+降级兼容。②**新建 `analysis/`**（非交付件、纯 stdlib）：`parser`(按 Startup 切分会话)→`metrics`(交付/鲜度归因/卡死段/阻塞/预算漂移/窗口/设卡ROI/RUSH时点/直方图)→`diagnose`(10 类 Finding)→`report`/`corpus`/`cli`(`python -m analysis`)。client 单测 115→138 + analysis 23，全通过；mock 端到端 @r81 交付、增厚日志验证（Block/opp/Budget/Start 地图角色）；`py -m analysis` 报告正确检出 OFFENSIVE_BACKFIRE、鲜度归因、RUSH 时点，数值与日志一致 | 真机日志可结构化归因，驱动后续迭代 | `CHANGELOG.md` |
| Iteration 13 | 2026-07-04 | 真机归因驱动的策略优化（任务分/鲜度/RUSH 时点） | 7 场真机归因（reports/20260704_corpus.md）：7/7 全交付但胜率仅 3/7，丢分集中在任务分缺口(对手180/我90~150)、鲜度崩盘(7/7跨阈值)、交付偏慢(均469帧,RUSH r450→r492 验核42帧空隙)。①**P1**`TASK_SEEK_TARGET 90→150`（任务分1:1涨至180,90以上用时分饱和但任务分仍净增）。②**P2**新增`TASK_DETOUR_SAFETY_MARGIN=15`,`_can_afford`加`safety_margin`形参,任务绕路用15帧余量释放预算(其余仍25)。③**P3**`CLAIM_ICE_BOX_KEEP 2→3`+冰鉴领取豁免`_can_afford`(2帧<3.6分/果,7/7跨80阈值根因)。④**P4**新增`RUSH_PREPOSITION_ROUND=360`,`_late_route_target`:round≥360未验核时直奔宫门不再绕路做任务。⑤**P5**`OFFENSIVE_MIN_OPP_DELAY 12→18`+`_opp_will_pass` fallback改False(不确信不种,减S10反噬)。新增6项单测(共144)+analysis 23全通过;mock端到端@r81交付fresh95.95/good99无回归;logs/README加"原始trace必须保留"纪律 | 在保7/7交付前提下追平任务分、保障鲜度、对齐RUSH时点,预期翻3~4场小分差负局 | `CHANGELOG.md` |
| Iteration 14 | 2026-07-04 | mock 保真度对齐真机（移动结算/天气/鲜度/好果转坏） | 真机交付均 469.6 帧，mock 仅 @r48~81（每条 MOVE 恒 2 帧、鲜度恒−0.05、无天气），无法验证 Iter13 后期逻辑（RUSH前置r360/鲜度阈值/任务预算）。`scripts/mock_server.py`（非交付件）按 §2.3.2/§2.5/§3.2 真实化：①`build_edges` 边表带 distance/routeType/coef；②MOVE 起步按 `ceil(距离×耗时系数)` 设移动量，`_tick_move` 按 `floor(基础×1000÷天气倍率)` 累计推进（替换固定 timer=1）；③4 次天气确定性排期(HOT r100/RAIN r220/FOG r340/HOT r460)按路线类型施减速+鲜度系数；④鲜度按路线类型 0.045~0.07×天气×急策（替换恒 0.05）；⑤跨 90/80/…/10 阈值触发好果转坏(`badFruit`纳入snapshot)；⑥RUSH r450 强制触发(§6.5)；⑦默认帧数 250→600。mock 端到端 @r459 交付 fresh=74.79 good=97 task=90（跨 80 阈值，与真机均值差 2%），RUSH_PROTECT/SCOUT_MARKER_CONSUME(验核6→3)/SQUAD_CLEAR预清障/SET_GUARD+增援 全路径首次被 mock 验证；client 144 单测不受影响 | mock 回归结论可覆盖后期逻辑；为后续真机迭代提供可信仿真底座 | `CHANGELOG.md` |
| Iteration 15 | 2026-07-04 | 真机 7 场报告归因驱动（任务分缺口 + 鲜度/冰鉴强化） | 7 场归因（reports/20260704_*.md）：3胜4负，7/7 交付，均 469.6 帧/鲜度 77.28。4 场任务分恰卡 150（旧 TASK_SEEK_TARGET）、对手稳定 180，单场丢 30 分（113730 -2、120537 -12 正好翻盘所需）；7/7 鲜度崩盘（均 77.28，跨 90/80 阈值各失 1 篒好果）。①**P1**`TASK_SEEK_TARGET 150→180`：对齐对手，4 场卡 150 的可继续绕路做任务至 180（base≥110 里程碑+50 封顶，90 以上用时分饱和故额外任务仅付小成本换 +30 任务分）。②**P2**冰鉴使用逻辑修正：`_freshness_rescue` 鲜度≤90 即用（+10 为交付前永久偏移，线性损耗下无论何时用最终鲜度都+10，前提不撞 100 上限），替换旧"仅近阈值≤7 使用"过保守逻辑。③**P3（用户优先鲜度诉求）**新增`_ice_box_detour_target` 绕路收集冰鉴：投影交付鲜度<85 且已持<2 时绕路去冰鉴节点，净鲜度收益(+10−绕路额外损耗)≥6 才绕（排除山路 S06 高损耗绕路，保留官道 S03→S07 且不丢下游任务节点），60 帧绕路范围内且时间预算允许。新增 2 项单测（共 146）+ analysis 23 全通过；mock 端到端：收 2 个冰鉴(+20 偏移)，**fresh 74.79→90.57、good 97→98（保 80 阈值）、task 90 不变、交付 r459→r482**，净 +27 分（+28 鲜度+1.8 好果−2.7 用时分） | 预期翻 2 场小分差负局（113730/120537 任务+30）；鲜度 77→90+ 跨过 80 阈值省好果+涨鲜度分，4 场鲜度崩盘局显著改善；以时间换鲜度符合用户诉求 | `CHANGELOG.md` |
| Iteration 16 | 2026-07-04 | 平台 PK 反馈任务分做不满（对手不动也达不到 180） | 根因：`config.SKIP_TASK_TEMPLATES=("T04","T06")` 按模板 ID 硬编码跳过 2/5 模板——T06 从不做、T04 仅突破时做，5 模板地图最多 3 任务=base90→任务分 125，结构性到不了 180；且硬编码地图一变即失效。①**P1**取消 `SKIP_TASK_TEMPLATES`，改协议动态评估：`GameContext` 缓存 `task_template_map`，新增 7 个纯函数判定器读 `processType`/`requiredResourceTypes`/`requiredFreshness`/`score`。②**P2**T06 持马即做 + `_horse_requiring_task_ahead` 保留马给前方 T06（30 分 > ~1 用时分）。③**P3**T04 按 `processType==CLEAR_OBSTACLE` 判定、支持 §5.2 相邻节点处理、突破/机会式/绕路三路径(优于 CLEAR)。④**P4**封顶停止条件 base≥180→`_task_score_capped`(base≥130)，`TASK_SEEK_TARGET=130`。⑤**P5**机会式做任务用紧余量 15。新增 6 项单测(共 151)+analysis 23 全通过；mock 端到端 5 任务全做(T01@S09/T02@S11/T06@S11/T04@S12 相邻/T01@S13)，**taskScore 90→150(最终任务分 180)**，交付@r494 fresh=89.61 good=98 | 任务分结构性缺口消除：5 模板地图可达 180 封顶(对标对手)；T06/T04 不再跳过；地图变化自动适配(协议驱动)；马匹保留给 T06 而非加速 | `CHANGELOG.md` |
| Iteration 17 | 2026-07-04 | 平台 PK 反馈窗口 PK 一直输 | 核查协议 §5.4.4 胜负表确认克制表 `_BEATS` 正确，根因在策略与成本门控：①中筹码(TASK/OBSTACLE)鲜度<80 时 `allow_bing=stakes>=3` 禁 BING + `allow_xian` 要 fresh>=80 → 只能 ABSTAIN → 0-2 输、丢 30 分；②"无法克制即弃权"在鲜度<80 错误(BING 近无敌应继续出)；③护卫点 4 点无预算分配、高筹码 BING×3 平局即耗光；④mock 完全未实现窗口争夺，从未端到端验证。**P1**新增 `_allow_bing(me,stakes)`：GATE/PASS `guard>=1`即用、TASK/OBSTACLE `guard>WINDOW_BING_RESERVE(1)`解禁、RESOURCE/DOCK 不花。**P2**重写 `_window_card`→`_choose_card`：有对手上拍信息时优先克制→同牌求平→`_strongest_available`(BING>XIAN>QIANG>YAN)，**不弃权白送胜点**。**P3**`_lead_card` 确定性优先级(BING>XIAN>QIANG>YAN)，鲜度<80 优先 BING。**P4**`_opp_last_card` cards key 双兼容(颜色/playerId)。新增 5 项单测(共 156)+analysis 23 全通过；现有 5 项窗口单测不破 | 鲜度<80(真机常态)窗口不再 0-2 空手输：BING 保平/克制取胜；中筹码任务窗口可花护卫点争夺；护卫点按价值预留；cards key 双兼容。反 exploitation 混合出牌为后续 lever | `CHANGELOG.md` |
| Iteration 18 | 2026-07-04 | 博弈审查驱动（对 decision.py 做博弈算法视角审查发现 8 类问题） | 实现其中 7 项：**P1**多窗口优先级 `_contest_priority`(筹码×100+速胜关门+后拍紧迫+deadline)替代纯筹码排序，避免紧迫窗口被弃权丢胜点。**P2**马匹统一预算 `reserve_horse`：本帧马被加速占用 OR 前方有需马 T06(+30 分)时窗口 QIANG 不消耗马(已有 buff 免消耗除外)，防 QIANG 吃 T06 的马 + 同帧加速/QIANG 双扣。**P3**`_keep_moving` 用马时同帧并发 `[horse, MOVE(next)]`(不同动作类别不互占额度§4.1)，杜绝"用马不发 MOVE→park 成 WAITING"卡死复发(mock r370 验证)。**P4**`_BEATS[YAN_DIE]` 改 `(BING, XIAN)`：反制对手 YAN 优先 BING(护卫点机会成本<好果)。**P5**`_can_break` 新增 `bo_bonus` 形参，`_enter_cost_fn` 计入 RUSH 破关令 +3，路由代价与 `_plan_attack` 实际攻坚一致，消除 RUSH 误绕路。**P6**`config.WINDOW_MIXED_LEAD` lever(默认关)：开启后 R1 按权重 BING0.5/XIAN0.25/QIANG0.15/YAN0.10 混合领出，roll 由 contestId+roundIndex+round+playerId 哈希(确定性可复现)，反剥削。**P7**清理死代码：移除 `_triggered`/`_prev_freshness`/`_track_freshness`/`_next_untriggered_threshold` 及 config 三个无引用兼容常量。**P8(mock)**补全 `scripts/mock_server.py` 窗口争夺仿真：3 拍流程+REVEAL 事件+cards 字段(颜色 key)+牌成本扣减(护卫点/好果/马/过所，红方 guardActionPoint 改动态)+胜负授予(RESOURCE/TASK)；触发点 `("S11","CLAIM_TASK","TK2")`（仅 TASK 中筹码；RESOURCE 低筹码不触发，因红方 stakes1 下无牌可出=策略层真实缺口）；蓝方虚拟资源池出牌(刻意偏弱保交付稳定)。client 156 + analysis 23 全通过；mock 端到端 S11 TASK 窗口 2-0 胜(BING→XIAN 反制→BING)，交付@r497 fresh=89.38 good=97 task=150 | 窗口多并发不再丢紧迫拍；马匹不再被窗口误吃；用马不 park 卡死；RUSH 路由一致；反剥削 lever 就绪；死代码清理降低调参误读；**窗口出牌策略首次端到端验证跑通**(反应式出牌/克制/成本/揭示读取/胜负授予全链路)；暴露低筹码 RESOURCE 窗口无牌可出的策略缺口 | `CHANGELOG.md` |
| Iteration 19 | 2026-07-04 | 修补 Iter18 暴露的低筹码窗口策略缺口 | 根因：`_allow_bing` 对 stakes1(RESOURCE/DOCK)一律 False，而红方不领过所/官凭、马只领 1 匹，stakes1 下 BING/XIAN 被关、YAN 无过所、QIANG 输 YAN/BING → 只能 ABSTAIN 必输。**P1**`_allow_bing` 新增 stakes1 分支：`g > WINDOW_BING_LOW_STAKES_RESERVE`(2) 时解禁 BING——BING 胜 YAN/QIANG、平 BING、仅负 XIAN，是低筹码下唯一能赢/平的牌；保留 2 点给中/高筹码(stakes2 需 g>1、stakes3 需 g>=1)，最多花 2 次(4→3→2)。**P2(mock)**`WINDOW_TRIGGERS` 加 `("S03","CLAIM_RESOURCE","ICE_BOX")` 触发 RESOURCE 窗口端到端验证。改 2 项低筹码窗口单测(gp=4 从 ABSTAIN 翻为 BING)+ 新增 gp=2 保留断言，client 156→157 + analysis 23 全通过；mock 端到端 S03 RESOURCE 窗口 1-0 胜(BING 领出平→BING 胜弃权→ABSTAIN 平，获 ICE_BOX)+ S11 TASK 窗口 2-0 胜，交付@r498 fresh=89.30 good=96 task=150 | 低筹码窗口不再 ABSTAIN 必输：guard 充足时 BING 争胜/求平；RESOURCE 窗口端到端验证跑通；护卫点按筹码分级预留(高>中>低)不致 GATE 无 BING | `CHANGELOG.md` |
