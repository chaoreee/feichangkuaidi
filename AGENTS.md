# AGENTS.md — 项目能力基线（Single Source of Truth）

> 本文件是《一骑红尘：荔枝争运战》Agent 交付件开发系统的**唯一能力基线**。
> 所有开发以本文件为依据；每次能力发生变化时**必须同步更新**本文件的"能力矩阵"与"迭代日志"。

- 最后更新：2026-07-03
- 当前轮次：Iteration 14（M8 博弈投影层 P2 终局交付 race §5.3：`decision.py` `_endgame_race_state`+race-aware `_rush_speed_warranted`——RUSH 相位对手将在 `ENDGAME_RACE_WINDOW` 帧内交付且我方也接近时，落后/接近放宽疾行门槛抢交付帧、领先抑制疾行留急策护果；鲜度危急/持马不疾行；非 race 保持原门槛。11 项新单测(共 156)全通过；mock 零回归 @r48）
- 上一轮次：Iteration 13（M8 博弈投影层 P2 悬赏机会主义 §5.2：`decision.py` `_maybe_bounty` 顺路/近路低代价破对手卡拿破关悬赏，过 `_can_afford`+ΔEV 地板(`BOUNTY_MIN_NET_SCORE`)+绕路上限(`BOUNTY_MAX_EXTRA_FRAMES`)；相邻破卡/否则靠近；CONSERVATIVE/RUSH 不追。10 项新单测(共 145)全通过；mock 零回归 @r48）
- 更早轮次：Iteration 12（M8 博弈投影层 P2 档位调参接入决策：`decision.py` 每帧按 mode 刷新 `StrategyTuning`；`_task_detour_target` 用档位绕路目标/上限并新增 §3.3 ΔEV 地板（`net_score_delta≥阈值`，读任务 `score`）；护果令阈值按档位（AGGRESSIVE 75）。`tuning.py` 增 `rush_protect_freshness_below`；config 增 `AGGRESSIVE_RUSH_PROTECT_FRESHNESS_BELOW`。9 项新单测(共 135)全通过；mock 仍 @r48 交付（EVEN=既有默认，零回归）。P2 行3/5 与 §5.2-5.4 仍待做）
- 规则来源：`一骑红尘：荔枝争运战 参赛选手任务书.md`、`一骑红尘：荔枝争运战 通信协议.md`（二者为最高权威，本文件与其冲突时以原始文档为准）

---

## 1. 项目目标与胜负口径

- **目标**：交付一个可提交比赛平台的 Python 客户端（Client），并建立"日志→分析→优化→更新基线"的持续迭代闭环。
- **局内胜负**（任务书 §1.3 / §7）：比赛结束时最终总分高者胜；总分相同直接判平。最终总分 = 送达基础分 + 皇榜任务分 + 用时分 + 好果数量分 + 鲜度品质分 + 破关悬赏分 − 惩罚，最低计 0。
- **平台积分**（任务书 §9）：正常参赛比总分（胜 3 / 负 0）；平分决胜按 鲜度→好果→惩罚 顺序。**未交付则送达/好果/鲜度/用时四项全为 0**，任务分封顶 80、悬赏封顶 25 —— 故"稳定交付"是第一优先。

## 2. 当前系统架构

三层：能力基线（本文件 + docs/）→ 运行期 Client（`client/`，纯 stdlib、可提交、离线可跑）→ 迭代闭环（取回 trace 日志由 Claude Code 直接分析）。
`client/` **本身即提交平台的交付件根目录**：`start.sh` 与 `main.py` 同级，手动打包时 `client/` 的内容直接构成 ZIP 根（不套同名目录）。运行期 trace 日志写在包内 `client/logs/`，随交付件下载回本地后复制到仓库 `logs/`（client 之外）供分析。仓库不再保留 python 分析模块与打包脚本。数据流与模块协作见 `docs/architecture.md`。
`samples/` 存放参考样例：`map_config.json`（✅ 已提供，中等难度竞技地图原始配置，为 `start` 载荷子集）；`start_message.json`/`inquire_message.json`（⛔ 暂不提供，结构以通信协议 §5/§7 + `docs/protocol.md` 为准）。只读，不被 `client/` import。字段差异详见 `samples/README.md`。

## 3. Agent 职责与工作原则

1. AGENTS.md 是唯一能力基线（SSOT）。
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
| 皇榜任务取舍（机会式 + 预算内绕路）+ 鲜度管理 | ✅ | 目标即当前节点直接做；任务分<90 且预算允许时向近处任务节点绕路；预算守卫计入验核耗时 |
| 移动/等待中主动续行（防卡死，保交付） | ✅ | `_keep_moving`：MOVING/WAITING 每帧重发 MOVE 到当前目标续行（协议允许、不清进度），无在途目标则重规划——杜绝空动作空等卡死（真实败局：卡在 S14/WAITING 至 600 帧未交付） |
| 阻塞感知路由（障碍/敌卡绕行） | ✅ | `time_optimal_path(blocked=...)`；仿真中障碍不可绕行时突破 |
| 突破：障碍→T04/CLEAR/强制通行 + 绕行/清障代价权衡 | ✅ | `_breakthrough`；绕行远超就地清障成本时改为清障；保留最低好果 |
| 突破：敌方设卡→攻坚破卡(含破关令)/强制通行 | ✅ | `_plan_attack` 最小投入达防守值，RUSH 绑破关令+3；不够则强制通行；单测覆盖 |
| 窗口出牌（响应本方窗口） | ✅ | `_window_card` 按可支付牌(兵争/献贡/验牒/强行)否则弃权 |
| 终局急策 疾行令/护果令（二选一）+ 破关令 | ✅ | 低鲜度护果令、畅通且远且无马用疾行令、攻坚绑破关令 |
| 小分队探路宫门（减验核 3 帧） | ✅ | `_maybe_squad`；仿真验核 6→3 帧 |
| 防御性小分队：预清路线障碍(SQUAD_CLEAR)/削弱前方敌卡(SQUAD_WEAKEN) | ✅ | 阻塞在路径第 2 跳后由小分队预处理；仿真 SQUAD_CLEAR 提前清障，主车队免耗好果(交付好果 100) |
| 主动设卡(SET_GUARD)/增援等进攻干扰 | 🟡 | 已实现关键关隘设卡逻辑，`config.ENABLE_OFFENSIVE` 默认关闭（delivery-first，占用己方交付时间）；单测覆盖开/关 |
| 博弈投影总线（Layer 1，纯观测） | ✅ | `strategy/projection.py`：每帧投影双方终局分/交付帧→gap→mode(保守/均衡/进取)，带滞后+低置信回落 EVEN；`Projector` 只写 trace、**不改任何动作**（P1 端到端逐帧一致，mock 仍 @r48 交付）；main 每帧输出 `Projection`、切档输出 `ModeChange` |
| 分数质量地板 ΔEV（§3.3，P1.5） | ✅ | `projection.net_score_delta`：纯函数估算增量动作对投影终局分的净影响；供 P2+ 增量动作与 `_can_afford` 组成与门；单测覆盖正/负 ΔEV 与烧好果败局模式 |
| 档位参数映射（Layer 2，§5.1） | ✅ | `strategy/tuning.py` `tuning_for_mode`：mode→{task_seek_target/detour 上限/ΔEV 阈值/护果令阈值}；EVEN 严格等于既有默认；三档 ΔEV 阈值均非负。**已被决策消费**（见下行） |
| P2 档位调参接入决策（§5.1 行1/2/4 + §3.3 ΔEV 地板） | ✅ | `decision.py` 每帧 `tuning_for_mode(mode)` 刷新参数：`_task_detour_target` 用档位绕路目标/上限并过 ΔEV 地板（`net_score_delta≥阈值`，读任务 `score`）——防 AGGRESSIVE 放宽上限后重演 839cfc9 烧好果败局；`_maybe_rush_protect`/`_rush_speed_warranted` 用档位护果令阈值（AGGRESSIVE 75、余 90）。mock 仍 @r48 交付（EVEN=既有默认）；9 项单测覆盖三档绕路差异/ΔEV 拒低价值/护果令时机 |
| P2 悬赏机会主义（§5.2） | ✅ | `decision.py` `_maybe_bounty`：顺路/近路低代价破对手有效设卡拿破关悬赏——`_plan_attack` 低成本可破 + 额外帧≤`BOUNTY_MAX_EXTRA_FRAMES`(25) + `_can_afford` + `net_score_delta≥BOUNTY_MIN_NET_SCORE`(15，计悬赏得分含+20交付奖−烧好果−耗时/鲜度)。相邻→`BREAK_GUARD`，否则沿绕开其它阻塞的路径靠近；CONSERVATIVE 锁胜/RUSH 保交付时不追。10 项单测覆盖破卡/靠近/高防守·自方卡·远绕路·零收益·已完成跳过 |
| P2 终局交付 race（§5.3） | ✅ | `decision.py` `_endgame_race_state`+`_rush_speed_warranted`：RUSH 相位对手投影将在 `ENDGAME_RACE_WINDOW`(20) 帧内交付且我方也接近时——落后/接近(gap≤0)放宽"远离终点"门槛用 `RUSH_SPEED` 抢交付帧、领先则抑制疾行(留急策护果)；鲜度危急/持马仍不疾行。领先且鲜度临界的 `RUSH_PROTECT` 由既有 `_maybe_rush_protect` 覆盖。非 race 保持原门槛。11 项单测覆盖 |
| P2 其余（§5.1 行3 突破烧好果、行5 窗口出牌）+ §5.4 窗口 EV | ❌ | 待实现：行3/5 触碰交付关键的突破路径与窗口牌语义，需真实 trace 验证与游戏规则确认；§5.4 为新增机会动作。均须逐项过 `_can_afford`+ΔEV 地板、默认安全、真实 trace 验证为正后打开 |
| Layer 3-4（ETA/任务·资源 race/条件化 SET_GUARD） | ❌ | 待实现；子能力开关 `ENABLE_TASK_DENY`/`ENABLE_RESOURCE_DENY`/`ENABLE_CONDITIONAL_GUARD` 已登记默认关（见 `docs/game_theory_projection_strategy.md` §6-§7、P3-P4） |

### 4.4 日志与分析
| 能力 | 状态 | 备注 |
|---|---|---|
| 人类可读 trace 运行日志（握手/每帧状态/每个动作/错误/结算/异常） | ✅ | `logger/match_logger.py` 输出 `<时钟> <Event> matchId=..., round=..., k=v`；写**包内** `client/logs/match_{matchId}_{playerId}.log`，逐行 flush；事件 Startup/Register/Start/Ready/Frame/Action/Recv/Error/Over/Score/Shutdown |
| 赛后分析 | ✅ | 由 Claude Code 直接读取取回的 trace 日志（仓库 `logs/`，client 之外）产出结论并回写基线；**已移除 python `analysis/` 模块** |

### 4.5 交付工程
| 能力 | 状态 | 备注 |
|---|---|---|
| start.sh（`./start.sh <playerId> <host> <port>`，可执行） | ✅ | **位于 `client/` 内，与 main.py 同级**（= ZIP 根）；LF、+x（git 100755）、**无中文**，透传参数给同目录 `main.py` |
| 交付件即 `client/` + §10.7 自检 | ✅ | 手动打包：把 `client/` 内容压成 ZIP（start.sh 直接在 ZIP 根，不套同名目录）；**已移除打包脚本**，打包前剔除 `__pycache__/`、`logs/*.log`；对照 §10.7 逐项自查 |
| 纯 stdlib、离线、无现场安装 | ✅ | 零第三方依赖，仅 socket/json/threading/queue/os/time |

## 5. 当前问题与已知限制

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
- `world.opponent` 已进入投影总线（Layer 1，`strategy/projection.py`）并驱动 **P2 档位调参**（§5.1 行1/2/4）：`decision.py` 每帧按 mode 调节任务绕路目标/上限与护果令阈值，绕路动作过 §3.3 ΔEV 地板。但 mode 前中段因 confidence<0.55 恒为 EVEN（=既有默认），故实战差异主要出现在中后段切档时——须真实 trace 校准 `LEAD_SAFE`/confidence 后才会频繁生效。§5.2 悬赏机会主义（`_maybe_bounty` 顺路破卡拿悬赏）与 §5.3 终局交付 race（`_endgame_race_state`+race-aware `_rush_speed_warranted`：落后抢帧/领先护果）已接入。P2 行3/5（突破烧好果、窗口出牌）与 §5.4（窗口 EV）、Layer 3-4 仍未实现。
- 投影为观测层近似：交付鲜度用平均每帧损耗 `AVG_FRESHNESS_LOSS_PER_FRAME=0.06` 粗估（不含天气/急策/逐边路线类型），悬赏投影两侧同置 0（对称保守）。用于可解释与校准，不追求逐帧精确；`LEAD_SAFE=40`/`PROJECTION_MIN_CONFIDENCE=0.55` 等为初值，必须用真实 `logs/` trace 校准。对手 confidence 前中段偏低（mode 大概率停在 EVEN）为设计预期，mode 主战场在中后段。

## 6. 后续规划（Roadmap）

M0 文档基线（本轮，✅ 交付中）→ M1 通信打通 → M2 核心镜像 → M3 基线策略（稳定交付）→ M4 收益策略 → M5 对抗策略 → M6 分析闭环 → M7+ 按真实日志迭代。里程碑详情见 `docs/architecture.md` §Roadmap。

**M8 博弈投影层（P1+P1.5+P2 档位调参已实现，P2 其余与 P3-P4 待续）**：把 `world.opponent` 升级为策略一等输入，用"对手投影驱动的风险档位切换 + 分数质量地板"提升胜率与得分上限。落地顺序（详见 `docs/game_theory_projection_strategy.md` §10）：P0 真实 trace 败局归因（待真实 `logs/`）→ **✅ P1 投影总线**（纯观测）→ **✅ P1.5 分数质量地板** `net_score_delta` → **🟡 P2 低风险增量**（✅ §5.1 行1/2/4 档位调参+ΔEV 地板、✅ §5.2 悬赏机会主义、✅ §5.3 终局交付 race 接入 `decision.py`；待做 §5.1 行3/5 与 §5.4 窗口 EV）→ P3 中风险 race（ETA/任务/鲜度/资源，逐项开关）→ P4 条件化 SET_GUARD（ROI 最低、最后做）。铁律：所有增量动作须同时过 `_can_afford`（时间）与 `ΔEV≥0`（分数）；信息不足默认 `EVEN` 保持基线。**下一步**：①拿真实对局 trace 归因（P0）+ 校准 `LEAD_SAFE`/confidence/投影精度/`ENDGAME_RACE_WINDOW`；②接入 P2 剩余（窗口 EV §5.4）。

## 7. 迭代日志

| 轮次 | 日期 | 触发 | 主要改动 | 能力增量 | 关联 |
|---|---|---|---|---|---|
| Iteration 0 | 2026-07-02 | 项目初始化 | 建立 AGENTS.md、docs/（architecture/delivery_spec/protocol/task）、CHANGELOG、目录骨架；确定 IO 模型=阻塞 socket+双线程 | 文档基线成型 | `CHANGELOG.md` |
| Iteration 1 | 2026-07-02 | M1 通信打通 | 实现 framing/enums/messages/actions、双线程 TcpClient、JSONL logger、占位 DecisionEngine、config、main 启动闭环、start.sh、mock_server、framing 单测；端到端跑通 registration→over，全程空动作心跳不退赛 | 通信层可用 | `CHANGELOG.md` |
| Iteration 2 | 2026-07-02 | M2 核心镜像 | 实现 core：rules(规则公式镜像)、pathfind(Dijkstra)、game_map(GameMap 解析+寻路)、world_state(WorldState 每帧解析)；main/decision 接线为每帧构建 WorldState 传入 decide；新增 40 项单测全通过；mock 端到端回归通过 | 状态镜像+规则+寻路可用，M3 策略就绪 | `CHANGELOG.md` |
| Iteration 3 | 2026-07-02 | M3 基线策略 | `decide` 实现最短路推进→固定处理→宫门验核(RUSH)→交付；GameMap 增 process_nodes 解析；mock_server 升级为加载 map_config 的全流程仿真；新增 10 项策略单测(共 50)全通过；仿真跑通 @r60 交付成功(鲜度97/好果100) | 可稳定交付得分 | `CHANGELOG.md` |
| Iteration 4 | 2026-07-02 | M4 收益策略 | 时间感知路由(time_optimal_path 计入处理耗时)；机会式皇榜任务/资源领取/冰鉴保鲜/马加速/护果令，均过时间预算守卫；mock 扩展支持资源/任务/急策/buff；新增 17 项单测(共 67)全通过；仿真 @r51 交付(更早)+任务分60+领取用马 | 收益策略可用，交付更早更优 | `CHANGELOG.md` |
| Iteration 5 | 2026-07-02 | M5 对抗策略 | 阻塞感知路由(绕行)+突破(障碍 T04/CLEAR/强制通行、敌卡攻坚含破关令/强制通行)、窗口出牌、疾行令/护果令二选一、小分队探路宫门减验核；mock 加障碍/清障/小分队探路/验核减时；新增 14 项单测(共 81)全通过；仿真障碍突破CLEAR+探路使验核6→3帧+交付@r55(鲜97.25/任务60) | 遇阻能突破，具备对抗动作 | `CHANGELOG.md` |
| Iteration 6 | 2026-07-02 | M6 分析闭环与打包 | main 增每帧 frame 记录并修复 over 摘要丢字段的日志 bug；analysis/ 四件套(parser/evaluator/optimizer/report)+CLI，真实日志产出 analysis.md；scripts/build_zip.py 打包提交 ZIP 并执行 §10.7 自检(全 PASS)；新增 5 项分析单测(共 86)全通过 | 具备赛后分析闭环与可提交打包 | `CHANGELOG.md` |
| Iteration 7 | 2026-07-02 | M7 能力补全 | 错误码分类+拒绝反馈(PROCESS_REQUIRED强制处理/移动阻塞拉黑绕行)；情报探路减时(含可用性领取守卫)；绕行vs清障权衡；预算内绕路做任务；防御性小分队清障/削弱；主动设卡(flag默认关)；新增 10 项单测(共 91 client+5 analysis)全通过；仿真 SQUAD_CLEAR 预清障使交付好果保 100、@r48 交付 | 补齐部分/未实现能力，鲁棒性与得分提升 | `CHANGELOG.md` |
| Iteration 8 | 2026-07-02 | 真实败局 local-debug-l1（未交付、卡在 S14/WAITING 至 600 帧）驱动 | **修正误诊**（非超时）：根因为 MOVING/WAITING 被动发空动作从不重规划→交付前空等卡死。改 `_keep_moving` 主动续行(重发 MOVE 到目标；无在途目标则重规划)；回退误诊的交付冲刺+任务上限；mock 改为"路线边空动作被 park 成 WAITING"以复现并验证；analyzer 增卡死诊断；101 项单测通过，端到端不再卡死、@r48 交付 | 杜绝交付前任何位置卡死，保证交付 | `CHANGELOG.md` |
| Iteration 9 | 2026-07-02 | 交付件工程重构（提交格式对齐 + 日志重构） | ①`start.sh` 移入 `client/`（与 main.py 同级 = ZIP 根），删除中文注释，指向同目录 `main.py`，git 100755；`client/` 即交付件根目录。②`MatchLogger` 改为人类可读 trace（`<时钟> <Event> matchId=..., round=..., k=v`），日志落**包内** `client/logs/`（`resolve_log_dir` 改指 client 目录）；main 全量改用语义化 `trace()`（Startup/Register/Start/Ready/Frame/Action/Recv/Error/Over/Score/Shutdown），空动作显式记 `action=NONE`，仅超预算附 `ms`。③删除 `analysis/` 模块与 `scripts/build_zip.*`、`dist/`；分析改由 Claude Code 直接读 trace。④新增仓库 `logs/`（client 之外）为采集/分析目录 + README；`.gitignore` 改忽略 `client/logs/*.log`。⑤刷新 AGENTS/README/architecture/delivery_spec。96 项 client 单测通过，mock 端到端 @r48 交付、trace 日志格式正确 | 交付件可直接手动打包提交；日志精简可读、随包取回即分析 | `CHANGELOG.md` |
| Iteration 14 | 2026-07-03 | M8 博弈投影层 P2 终局交付 race（§5.3）接入决策 | `decision.py` 新增 `_endgame_race_state(world, me)`（RUSH 相位 + 对手投影 deliver_frame 与我方 deliver_frame 均在 `ENDGAME_RACE_WINDOW`(20) 帧内 → racing；`gap≤0` → behind）；`_rush_speed_warranted` 改为 race-aware：race 且落后/接近 → 放宽"远离终点"门槛用 `RUSH_SPEED` 抢交付帧，race 且领先 → 抑制疾行(不烧 +25% 鲜度，留急策护果)；鲜度危急/持马仍不疾行；非 race 维持原门槛。领先且鲜度临界的 `RUSH_PROTECT` 由既有 `_maybe_rush_protect` 覆盖。新增 `test_endgame_race.py` 11 项（落后近处抢帧/非race近处不冲/领先抑制/非race远处保持原疾行/鲜度危急不冲/持马不冲 + `_endgame_race_state` 各分支）共 +11（合计 156）全通过；mock 无对手推进/悬赏故零回归 @r48 | 终局据对手投影分差在"抢交付帧"与"锁交付质量"间取舍 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 13 | 2026-07-03 | M8 博弈投影层 P2 悬赏机会主义（§5.2）接入决策 | `decision.py` 新增 `_maybe_bounty`（在 `_plan` 的 opportunistic 之后、set_guard 之前）：遍历 `world.bounties`，对**对手有效设卡**且 `_plan_attack` 低成本可破的悬赏节点，计算绕开其它阻塞后的额外帧（`≤BOUNTY_MAX_EXTRA_FRAMES=25`）、过 `_can_afford` 与 `net_score_delta≥BOUNTY_MIN_NET_SCORE=15`（悬赏原始分作 `extra_bounty`，烧好果作 `good_fruit_burned`，额外耗时/鲜度计入）；相邻→`BREAK_GUARD`(最小投入,保好果下限)，否则沿路径 `MOVE` 靠近一步。CONSERVATIVE(锁胜)/RUSH(保交付) 不追悬赏。新增 `test_bounty_opportunism.py` 10 项（破卡/靠近/高防守·自方卡·远绕路·零收益·已完成跳过/CONSERVATIVE·RUSH 不追）共 +10（合计 145）全通过；mock 无悬赏数据故 `_maybe_bounty` 不触发、仍 @r48 交付零回归 | 破关悬赏成为顺路正 EV 收益来源，受 ΔEV 地板与档位/相位守卫保护交付下限 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 12 | 2026-07-03 | M8 博弈投影层 P2 档位调参接入决策 | `decision.py` 每帧 `tuning_for_mode(mode)` 刷新 `StrategyTuning`：①`_task_detour_target` 用档位 `task_seek_target`/`task_detour_max_extra_frames`，并新增 §3.3 ΔEV 地板守卫（`_detour_net_delta` 以本方投影为基线、计入额外耗时+鲜度损耗，读任务 `score` 作任务分增量；`< 档位阈值` 则拒绝绕路）；②`_maybe_rush_protect`/`_rush_speed_warranted` 改用档位护果令阈值。`tuning.py` `StrategyTuning` 增 `rush_protect_freshness_below`（CONSERVATIVE/EVEN=90、AGGRESSIVE=75）；`config.py` 增 `AGGRESSIVE_RUSH_PROTECT_FRESHNESS_BELOW=75`。新增 `test_mode_tuning_wiring.py`（三档绕路差异/AGGRESSIVE 放宽上限/ΔEV 拒低价值绕路且 AGGRESSIVE 也不放净负分/护果令时机）+ 扩 tuning 单测，共 +9（合计 135）全通过；mock 端到端仍 @r48 交付（mode 恒 EVEN=既有默认，零回归） | gap 驱动的档位参数正式改变动作（EVEN 之外档位切换时），且受 ΔEV 地板保护不做净负分绕路 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 11 | 2026-07-03 | M8 博弈投影层 P1+P1.5 落地（纯观测，不改动作） | 新增 `strategy/projection.py`：①`Projector` 每帧投影双方终局分/交付帧→gap→`ModeMachine`(滞后+低置信回落 EVEN)，产出只读 `ProjectionBus`；②`project_final_score` 复用 `core/rules.py` 组合投影分；③`net_score_delta`（§3.3 分数质量地板）纯函数估算增量动作 ΔEV。新增 `strategy/tuning.py` `tuning_for_mode`（Layer 2 档位参数，EVEN=既有默认，尚未被消费）。`decision.py` 每帧构建投影总线（异常安全、**不改任何动作**）；`main.py` 输出 `Projection`/`ModeChange` trace。`config.py` 增 §9 常量（LEAD_SAFE/滞后/置信阈值/ΔEV 三档/进取绕路上限 90/悬赏/子能力开关）。新增 4 个测试文件 30 项单测（共 126）全通过；mock 端到端仍 @r48 交付、动作逐帧一致，Projection trace 每帧输出、confidence 前段<0.55 故 mode 恒 EVEN（符合设计） | `world.opponent` 成为投影总线一等输入（纯观测）；分数质量地板与档位参数基础设施就绪，供 P2-P4 校准后接入 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 10 | 2026-07-03 | 博弈投影层设计评审与优化（未改运行期代码） | 依据代码/协议核对 `docs/game_theory_projection_strategy.md`：①**修正时序前提**——mock ~r48–r55 交付不代表实战，真实交付在 450+，据此确认存在约 450 帧争夺中局、上调 Layer 3/4 价值评估；②**新增分数质量地板 §3.3**（`ΔEV≥0`）——补 `_can_afford` 只守时间不守分数的缺口，防 AGGRESSIVE 重演 839cfc9 过度贪任务/烧好果；③AGGRESSIVE 绕路上限从直觉 120 收敛到 90；④明确投影 confidence 前段低、mode 主战场在中后段；⑤落地顺序改为 P1 纯观测先行 + P1.5 ΔEV 地板前置于任何改动作层。同步 AGENTS 能力矩阵（新增博弈层行）/Roadmap（M8）/已知限制 | 博弈层设计定稿、与历史败局教训对齐；实现前的规格就绪 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
