# CLAUDE.md — 项目能力基线（Single Source of Truth）

> 本文件是《一骑红尘：荔枝争运战》Agent 交付件开发系统的**唯一能力基线**。
> 所有开发以本文件为依据；每次能力发生变化时**必须同步更新**本文件的"能力矩阵"与"迭代日志"。

- 最后更新：2026-07-04
- 当前轮次：Iteration 21（**迭代方式重排设计评审**——未改运行期决策代码。三问分析认定：①20 轮/M8 全建在 mock@r48 之上、`logs/` 零真实 trace 的"验证真空"；②静态层是贪心瀑布未求解、任务冲 90 的 ~+220 分杠杆只被机会式处理；③博弈层优先级错置（SET_GUARD ROI 最低却占 P4，GATE/deny 最弱）。产出 `docs/iteration_plan_v2.md` 定新范式：**分析器驱动证据型迭代**——in-client 采集器+repo 聚合器把 10w 字 trace 压成结构化 report，AI 只做归因；Phase 0 真实 trace → A 高保真仿真(复用 `rules.py`) → B 静态规划器(任务-90 可达性) → C 仿真校准 → D 博弈层重排(GATE/deny/预测优先，SET_GUARD 冻结)。同步更新 architecture/delivery_spec/CHANGELOG。运行期代码与 mock @r48 零回归。）
- 上一轮次：Iteration 20（M8 P4 §7 条件化 SET_GUARD 默认关；M8 P1-P4 全部落地；15 项新单测共 229）。更早各轮见 §7 迭代日志。
- 进度：**迭代方式重排为分析器驱动证据型**（详见 `docs/iteration_plan_v2.md`）。M8 P1-P4 代码全部保留但 triage：Layer1/ΔEV/ETA 保留（ΔEV 输入待 Phase B 鲜度模型升级后才可信）、P2/P3 race 待仿真 A/B 后逐项开关、P4 SET_GUARD **冻结**。**下一步（Iter 21→）**：先建分析器基础设施（`client/analysis/collector.py` + `scripts/analyze_logs.py` + report.json schema + 单测+对账），再 Phase 0 收割真实 trace，再 Phase A 高保真仿真、Phase B 静态规划器。新"done"标准：任何改动须过仿真 A/B 证据（见 `iteration_plan_v2.md` §1.2）。
- 规则来源：`一骑红尘：荔枝争运战 参赛选手任务书.md`、`一骑红尘：荔枝争运战 通信协议.md`（二者为最高权威，本文件与其冲突时以原始文档为准）

---

## 1. 项目目标与胜负口径

- **目标**：交付一个可提交比赛平台的 Python 客户端（Client），并建立"日志→分析→优化→更新基线"的持续迭代闭环。
- **局内胜负**（任务书 §1.3 / §7）：比赛结束时最终总分高者胜；总分相同直接判平。最终总分 = 送达基础分 + 皇榜任务分 + 用时分 + 好果数量分 + 鲜度品质分 + 破关悬赏分 − 惩罚，最低计 0。
- **平台积分**（任务书 §9）：正常参赛比总分（胜 3 / 负 0）；平分决胜按 鲜度→好果→惩罚 顺序。**未交付则送达/好果/鲜度/用时四项全为 0**，任务分封顶 80、悬赏封顶 25 —— 故"稳定交付"是第一优先。

## 2. 当前系统架构

三层：能力基线（本文件 + docs/）→ 运行期 Client（`client/`，纯 stdlib、可提交、离线可跑）→ 迭代闭环（**分析器驱动**：in-client 采集器把对局压成结构化 `report.json` → repo 侧聚合器产出跨局/A/B 聚合报告 → Claude Code 读聚合报告做归因，不再直读 10w 字原始 trace）。
`client/` **本身即提交平台的交付件根目录**：`start.sh` 与 `main.py` 同级，手动打包时 `client/` 的内容直接构成 ZIP 根（不套同名目录）。运行期 trace 日志 + `report.json` 写在包内 `client/logs/`，随交付件下载回本地后复制到仓库 `logs/`（client 之外）供分析。仓库不再保留打包脚本；分析改为 `client/analysis/collector.py`（包内采集）+ `scripts/analyze_logs.py`（仓库侧聚合）两层，**只抽取事实、不做优化**（Iteration 9 删旧 `analysis/` 后以正确形态回归，详见 `docs/iteration_plan_v2.md`）。数据流与模块协作见 `docs/architecture.md`。
`samples/` 存放参考样例：`map_config.json`（✅ 已提供，中等难度竞技地图原始配置，为 `start` 载荷子集）；`start_message.json`/`inquire_message.json`（⛔ 暂不提供，结构以通信协议 §5/§7 + `docs/protocol.md` 为准）。只读，不被 `client/` import。字段差异详见 `samples/README.md`。

## 3. Agent 职责与工作原则

1. CLAUDE.md 是唯一能力基线（SSOT）。
2. 所有代码实现严格遵循 `docs/delivery_spec.md`。
3. 所有实现严格符合任务书与通信协议。
4. 运行期 trace 日志 + 结构化 `report.json` 写在包内 `client/logs/match_<matchId>_<playerId>.{log,json}`；取回后归档到仓库 `logs/`（client 之外）可追溯。
5. 每轮日志分析：in-client 采集器产出 `report.json`（事实，纯代码抽取），repo 侧 `scripts/analyze_logs.py` 聚合产出跨局/A/B 报告，Claude Code 读聚合报告做归因（**代码抽取事实、AI 只做解释**；分析器不做优化）。
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
| P2 窗口 EV / 出牌（§5.4 + §5.1 行5） | ✅ | `decision.py` `_window_card` 重构为代价感知+档位门控：无代价牌(兵争行动点/验牒文书/免费强行 buff——均不影响交付)按克制强度恒出(弱优于弃权)；献贡(烧 1 好果=减交付分)仅非 CONSERVATIVE 且窗口价值明显(`WINDOW_VALUABLE_CONTEST_TYPES`)、好果高于档位下限(`WINDOW_XIANGONG_MIN_GOOD_*`)、鲜度≥80 时出；不为窗口烧马(马留交付提速)；CONSERVATIVE 只出无代价牌/弃权。14 项单测覆盖。（未接入对手出牌倾向预测——需可靠历史与真实 trace，暂缓） |
| P2 突破烧好果意愿（§5.1 行3） | ✅ | `decision.py` `_breakthrough`+`_prefer_forced_pass`：CONSERVATIVE(领先锁好果)且强制通行时间税仍能按时交付(`_forced_pass_tax`+`_can_afford`)时，突破优先 `FORCED_PASS` 不烧好果(障碍与敌卡皆是)；负担不起则回退 CLEAR/BREAK_GUARD 烧好果保交付下限。EVEN/AGGRESSIVE 保持烧好果攻坚(更快)。tuning 增 `protect_good_fruit_on_breakthrough`。10 项单测覆盖。**必要突破前提下只改"方法"不改"是否突破"** |
| P3 对手轨迹 ETA（§6.1，纯观测） | ✅ | `projection.py` `OpponentEta`+`Projector.build_opponent_eta`：估算对手到宫门/终点/任务点/资源点帧数（在途按 `move_progress` 加残余帧、未验核 to_finish 计验核耗时）；置信随终局上升、轨迹频繁变化(原地改目标)打折。`decision.py` 每帧构建存 `self.opponent_eta`、**不改动作**；main 每帧 `Eta` trace。8 项单测覆盖。只作后续 race 的 tie-breaker/争夺判断输入 |
| P3 任务 race（§6.2，默认关） | ✅(默认关) | `decision.py` 两子能力，各带开关：**追平**(`ENABLE_TASK_RACE`)——对手任务分≥`TASK_RACE_OPP_THRESHOLD`(80,逼近90)且我方<90 时 `_task_detour_target` 放宽绕路目标(≥90)/上限(→AGGRESSIVE)，仍过 `_can_afford`+ΔEV 地板；**Deny**(`ENABLE_TASK_DENY`)——`_task_deny_target` 用 §6.1 ETA 抢占对手正奔赴、我方到达帧数≤对手 ETA、且跨对手里程碑(60/90/110)的可领取任务点，过 `_can_afford`+净分≥0+不跑空趟。14 项单测覆盖。默认关，待真实 trace 验证为正后开 |
| P3 鲜度/资源 race（§6.3，默认关） | ✅(默认关) | `decision.py` 两子能力各带开关：**鲜度 race**(`ENABLE_FRESHNESS_RACE`)——对手鲜度比我方高≥`FRESHNESS_RACE_GAP`(处劣势)时 `_freshness_rescue` 把冰鉴使用阈值提到 `ICE_BOX_RACE_USE_BELOW`(88) 提前保阈值；**资源 race**(`ENABLE_RESOURCE_DENY`)——`_maybe_resource_race` 用 §6.1 ETA 抢占对手正争夺、我方到达帧数≤对手 ETA、库存有限的路线附近冰鉴(额外帧≤`RESOURCE_RACE_MAX_EXTRA_FRAMES` 不显著偏离、过 `_can_afford`、未囤够 `RESOURCE_RACE_ICEBOX_KEEP`)。12 项单测覆盖。默认关，待真实 trace 验证后开 |
| P4 条件化 SET_GUARD（§7，默认关） | ✅(默认关) | `decision.py` `_maybe_set_guard` 分发：`ENABLE_CONDITIONAL_GUARD`→`_conditional_guard`（§7.1 六条件：CONSERVATIVE+`gap≥GUARD_MIN_LEAD`、当前节点为关键关隘、对手 ETA∈`(GUARD_SETUP_FRAMES, GUARD_SURVIVAL_WINDOW]`、投入好果后守 `GUARD_KEEP_GOOD_FRUIT`、`_can_afford`、`eta.confidence≥GUARD_MIN_CONFIDENCE`）+ denial 期望分损失 `_guard_denial_value`（对手破卡[受好/坏果≤2 约束]与强制通行取更省者）≥`GUARD_MIN_NET_VALUE`；否则 `ENABLE_OFFENSIVE`→`_basic_set_guard`（M7 基线）。设卡细节写 `guard_decision`，main 每帧 `GuardDecision` trace。15 项单测。默认关，ROI 最低待真实 trace 验证 |

### 4.4 日志与分析
| 能力 | 状态 | 备注 |
|---|---|---|
| 人类可读 trace 运行日志（握手/每帧状态/每个动作/错误/结算/异常） | ✅ | `logger/match_logger.py` 输出 `<时钟> <Event> matchId=..., round=..., k=v`；写**包内** `client/logs/match_{matchId}_{playerId}.log`，逐行 flush；事件 Startup/Register/Start/Ready/Frame/Action/Recv/Error/Over/Score/Shutdown |
| 赛后分析 | 🟡(规划中) | **Iteration 21 重排为分析器驱动**（详见 `docs/iteration_plan_v2.md`）：in-client `client/analysis/collector.py` 运行时累计决策事件、game over 写 `report.json`（2-4KB 结构化事实，schemaVersion 化）；repo 侧 `scripts/analyze_logs.py` **累积语料**（跨批次追加，单次提交对局少也够样本）+ 跨局统计 + **场景分段**（交付/未交付、task-90 达成/未达、中局领先/落后、天气/争抢 等）+ seed 配对 A/B + **运气分类**（expected_win/unlucky_loss/lucky_win/expected_loss）+ 异常局标记 + `rules.py` 对账自检 → `analysis_report.md`/`ab_report.md`/`calibration_v1.md` 三份分工报告；Claude Code 读聚合报告归因，不直读 10w 字 trace。**代码只抽取事实、不做优化**；**单局只作假设来源，决策须基于全语料聚合+CI+分段不回归**（防单点过拟合，对齐 839cfc9 教训）。实现待 Iter 21 |

### 4.5 交付工程
| 能力 | 状态 | 备注 |
|---|---|---|
| start.sh（`./start.sh <playerId> <host> <port>`，可执行） | ✅ | **位于 `client/` 内，与 main.py 同级**（= ZIP 根）；LF、+x（git 100755）、**无中文**，透传参数给同目录 `main.py` |
| 交付件即 `client/` + §10.7 自检 | ✅ | 手动打包：把 `client/` 内容压成 ZIP（start.sh 直接在 ZIP 根，不套同名目录）；**已移除打包脚本**，打包前剔除 `__pycache__/`、`logs/*.log`；对照 §10.7 逐项自查 |
| 纯 stdlib、离线、无现场安装 | ✅ | 零第三方依赖，仅 socket/json/threading/queue/os/time |

## 5. 当前问题与已知限制

- **〔Iteration 21 三问分析认定，最高优先〕验证真空 + 静态层未求解 + 博弈层优先级错置**：① 20 轮/M8 P1-P4 全建在 mock@r48 之上，仓库 `logs/` **零真实对局 trace**，所有阈值/开关均为未校准初值、`ENABLE_*` 全默认关、mode 在唯一测试环境恒 EVEN → 博弈层对动作零影响；② 静态层 `_plan` 是贪心瀑布而非优化求解，任务冲 90（解锁送达基础分 120→240 + 用时系数满 + 里程碑 35，~+220 分）只被机会式处理，漏 90 代价远超 M8 微调；③ SET_GUARD ROI 最低却占 P4，GATE 验核/deny 收益最高却最弱。**处置见 `docs/iteration_plan_v2.md`：分析器驱动证据型迭代，Phase 0→A→B→C→D，SET_GUARD 冻结。** 在分析器 + 真实 trace + 仿真三级证据就绪前，不新增博弈层能力。
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
- 投影为观测层近似：交付鲜度用平均每帧损耗 `AVG_FRESHNESS_LOSS_PER_FRAME=0.06` 粗估（不含天气/急策/逐边路线类型），悬赏投影两侧同置 0（对称保守）。用于可解释与校准，不追求逐帧精确；`LEAD_SAFE=40`/`PROJECTION_MIN_CONFIDENCE=0.55` 等为初值，必须用真实 `logs/` trace 校准。对手 confidence 前中段偏低（mode 大概率停在 EVEN）为设计预期，mode 主战场在中后段。

## 6. 后续规划（Roadmap）

M0 文档基线 → M1 通信打通 → M2 核心镜像 → M3 基线策略（稳定交付）→ M4 收益策略 → M5 对抗策略 → M6 分析闭环 → M7 能力补全 → M8 博弈投影层（P1-P4 代码全部落地，待校准）→ **M9 分析器驱动证据型迭代（Iteration 21 起，进行中）**。里程碑详情见 `docs/architecture.md` §Roadmap。

**M8 博弈投影层（P1-P4 代码已实现，全部待校准/默认关）**：把 `world.opponent` 升级为策略一等输入，用"对手投影驱动的风险档位切换 + 分数质量地板"提升胜率与得分上限（详见 `docs/game_theory_projection_strategy.md`）。M8 P1-P4 代码全部保留，但 Iteration 21 triage 后：Layer1/ΔEV/ETA 保留（ΔEV 输入待 M9 Phase B 鲜度模型升级后才可信）、P2/P3 race 待仿真 A/B 后逐项开关、**P4 SET_GUARD 冻结**。铁律不变：所有增量动作须同时过 `_can_afford`（时间）与 `ΔEV≥0`（分数）；信息不足默认 `EVEN` 保持基线。

**M9 分析器驱动证据型迭代（Iteration 21 起，进行中，详见 `docs/iteration_plan_v2.md`）**：针对 Iteration 21 三问认定（验证真空 / 静态层未求解 / 博弈层优先级错置），把迭代方式改为证据型闭环 `假设→仿真/trace 证据→实现→A/B→仅当正向才固化`。落地顺序：**Iter 21 分析器基础设施**（in-client `collector.py` + `report.json` schema + repo `analyze_logs.py` + 单测+对账，只抽取不优化）→ **Phase 0** 真实 trace 收割 + P0 归因 → **Phase A** 高保真自博弈仿真器（物理复用 `core/rules.py`，产出同格式 report）→ **Phase B** 静态规划器（任务-90 可达性 + 路线评分 + 鲜度投影升级，替换 `_plan` 贪心瀑布）→ **Phase C** 仿真驱动阈值/开关校准（产出 `calibration_v1.md`）→ **Phase D** 博弈层重排（D1 GATE 验核 race、D2 窗口对手出牌预测、D3 deny 按 |gap| 条件化+相对分 ΔEV；D4 SET_GUARD 冻结）。新"done"标准见 `iteration_plan_v2.md` §1.2。

## 7. 迭代日志

| 轮次 | 日期 | 触发 | 主要改动 | 能力增量 | 关联 |
|---|---|---|---|---|---|
| Iteration 21 | 2026-07-04 | 策略三问分析（验证真空 / 静态层未求解 / 博弈层优先级错置）驱动迭代方式重排 | **未改运行期决策代码**。新增 `docs/iteration_plan_v2.md`（完整设计与实现说明）：定新范式"分析器驱动证据型迭代"——in-client 采集器 `client/analysis/collector.py` + repo 聚合器 `scripts/analyze_logs.py` 把 10w 字 trace 压成结构化 `report.json`(2-4KB) + 聚合报告，**代码只抽取事实、AI 只做解释**（Iter 9 删旧 `analysis/` 后以正确形态回归）。Phase 路线：0 真实 trace 归因 → A 高保真仿真(复用 `core/rules.py`) → B 静态规划器(任务-90 可达性替换贪心瀑布) → C 仿真校准 → D 博弈层重排(GATE/deny/预测优先，SET_GUARD 冻结)。新"done"标准：改动须过仿真 A/B 证据。同步更新 CLAUDE.md(能力矩阵增"赛后分析🟡规划中"、§5 增三问认定、§6 增 M9)、architecture.md(数据流增分析器漏斗、Roadmap 增 M9)、delivery_spec.md、CHANGELOG.md。M8 P1-P4 代码 triage：Layer1/ΔEV/ETA 保留、P2/P3 待 A/B、P4 冻结。运行期代码与 mock @r48 零回归 | 迭代方式重排为证据型；分析器/仿真器/静态规划器设计基线就绪，待 Iter 21+ 实现 | `CHANGELOG.md`、`docs/iteration_plan_v2.md` |
| Iteration 0 | 2026-07-02 | 项目初始化 | 建立 CLAUDE.md、docs/（architecture/delivery_spec/protocol/task）、CHANGELOG、目录骨架；确定 IO 模型=阻塞 socket+双线程 | 文档基线成型 | `CHANGELOG.md` |
| Iteration 1 | 2026-07-02 | M1 通信打通 | 实现 framing/enums/messages/actions、双线程 TcpClient、JSONL logger、占位 DecisionEngine、config、main 启动闭环、start.sh、mock_server、framing 单测；端到端跑通 registration→over，全程空动作心跳不退赛 | 通信层可用 | `CHANGELOG.md` |
| Iteration 2 | 2026-07-02 | M2 核心镜像 | 实现 core：rules(规则公式镜像)、pathfind(Dijkstra)、game_map(GameMap 解析+寻路)、world_state(WorldState 每帧解析)；main/decision 接线为每帧构建 WorldState 传入 decide；新增 40 项单测全通过；mock 端到端回归通过 | 状态镜像+规则+寻路可用，M3 策略就绪 | `CHANGELOG.md` |
| Iteration 3 | 2026-07-02 | M3 基线策略 | `decide` 实现最短路推进→固定处理→宫门验核(RUSH)→交付；GameMap 增 process_nodes 解析；mock_server 升级为加载 map_config 的全流程仿真；新增 10 项策略单测(共 50)全通过；仿真跑通 @r60 交付成功(鲜度97/好果100) | 可稳定交付得分 | `CHANGELOG.md` |
| Iteration 4 | 2026-07-02 | M4 收益策略 | 时间感知路由(time_optimal_path 计入处理耗时)；机会式皇榜任务/资源领取/冰鉴保鲜/马加速/护果令，均过时间预算守卫；mock 扩展支持资源/任务/急策/buff；新增 17 项单测(共 67)全通过；仿真 @r51 交付(更早)+任务分60+领取用马 | 收益策略可用，交付更早更优 | `CHANGELOG.md` |
| Iteration 5 | 2026-07-02 | M5 对抗策略 | 阻塞感知路由(绕行)+突破(障碍 T04/CLEAR/强制通行、敌卡攻坚含破关令/强制通行)、窗口出牌、疾行令/护果令二选一、小分队探路宫门减验核；mock 加障碍/清障/小分队探路/验核减时；新增 14 项单测(共 81)全通过；仿真障碍突破CLEAR+探路使验核6→3帧+交付@r55(鲜97.25/任务60) | 遇阻能突破，具备对抗动作 | `CHANGELOG.md` |
| Iteration 6 | 2026-07-02 | M6 分析闭环与打包 | main 增每帧 frame 记录并修复 over 摘要丢字段的日志 bug；analysis/ 四件套(parser/evaluator/optimizer/report)+CLI，真实日志产出 analysis.md；scripts/build_zip.py 打包提交 ZIP 并执行 §10.7 自检(全 PASS)；新增 5 项分析单测(共 86)全通过 | 具备赛后分析闭环与可提交打包 | `CHANGELOG.md` |
| Iteration 7 | 2026-07-02 | M7 能力补全 | 错误码分类+拒绝反馈(PROCESS_REQUIRED强制处理/移动阻塞拉黑绕行)；情报探路减时(含可用性领取守卫)；绕行vs清障权衡；预算内绕路做任务；防御性小分队清障/削弱；主动设卡(flag默认关)；新增 10 项单测(共 91 client+5 analysis)全通过；仿真 SQUAD_CLEAR 预清障使交付好果保 100、@r48 交付 | 补齐部分/未实现能力，鲁棒性与得分提升 | `CHANGELOG.md` |
| Iteration 8 | 2026-07-02 | 真实败局 local-debug-l1（未交付、卡在 S14/WAITING 至 600 帧）驱动 | **修正误诊**（非超时）：根因为 MOVING/WAITING 被动发空动作从不重规划→交付前空等卡死。改 `_keep_moving` 主动续行(重发 MOVE 到目标；无在途目标则重规划)；回退误诊的交付冲刺+任务上限；mock 改为"路线边空动作被 park 成 WAITING"以复现并验证；analyzer 增卡死诊断；101 项单测通过，端到端不再卡死、@r48 交付 | 杜绝交付前任何位置卡死，保证交付 | `CHANGELOG.md` |
| Iteration 9 | 2026-07-02 | 交付件工程重构（提交格式对齐 + 日志重构） | ①`start.sh` 移入 `client/`（与 main.py 同级 = ZIP 根），删除中文注释，指向同目录 `main.py`，git 100755；`client/` 即交付件根目录。②`MatchLogger` 改为人类可读 trace（`<时钟> <Event> matchId=..., round=..., k=v`），日志落**包内** `client/logs/`（`resolve_log_dir` 改指 client 目录）；main 全量改用语义化 `trace()`（Startup/Register/Start/Ready/Frame/Action/Recv/Error/Over/Score/Shutdown），空动作显式记 `action=NONE`，仅超预算附 `ms`。③删除 `analysis/` 模块与 `scripts/build_zip.*`、`dist/`；分析改由 Claude Code 直接读 trace。④新增仓库 `logs/`（client 之外）为采集/分析目录 + README；`.gitignore` 改忽略 `client/logs/*.log`。⑤刷新 AGENTS/README/architecture/delivery_spec。96 项 client 单测通过，mock 端到端 @r48 交付、trace 日志格式正确 | 交付件可直接手动打包提交；日志精简可读、随包取回即分析 | `CHANGELOG.md` |
| Iteration 20 | 2026-07-03 | M8 博弈投影层 P4 §7 条件化 SET_GUARD（默认关）——**M8 P1-P4 全部落地** | `decision.py` `_maybe_set_guard(world,me,gm,node,terminal)` 改为分发：`ENABLE_CONDITIONAL_GUARD`→`_conditional_guard`，否则 `ENABLE_OFFENSIVE`→`_basic_set_guard`(M7 基线保留)。`_conditional_guard` 落地 §7.1 六条件（CONSERVATIVE 且 `gap≥GUARD_MIN_LEAD`(60)；当前节点 type=KEY_PASS 且无有效卡；`eta.confidence≥GUARD_MIN_CONFIDENCE`(0.7)；对手 `eta.eta(node)∈(GUARD_SETUP_FRAMES(5), GUARD_SURVIVAL_WINDOW(60)]`；`_guard_extra_fruit` 选投入后仍守 `GUARD_KEEP_GOOD_FRUIT`(20) 的最大额外好果；`_can_afford(GUARD_SETUP_FRAMES)`）+ `_guard_denial_value`（对手撞卡期望分损失：破卡[好/坏果各≤2 约束，坏果不计分]与强制通行[`rules.guard_time_tax` 用时分]取更省者）≥`GUARD_MIN_NET_VALUE`(4)。设卡细节写 `self.guard_decision`（每帧 `_update_projection` 清空），`main.py` 每帧输出 `GuardDecision` trace（target/gap/oppEta/extraGood/defense/denial）。config 增 `GUARD_MIN_LEAD/CONFIDENCE/SETUP_FRAMES/SURVIVAL_WINDOW/KEEP_GOOD_FRUIT/MIN_NET_VALUE`。新增 `test_conditional_guard.py` 15 项（锁胜设卡；领先不足/非关隘/已有卡/置信低/ETA 窗口内外/好果不足/对手可低价破卡/任务分低 denial 不足；分发与基线并存）共 +15（合计 229）全通过；所有 race/guard 开关默认关故 mock 零回归 @r48 | 主动设卡从二元开关升级为投影驱动的条件开关（锁胜局用富余好果对对手施加破卡/强制通行代价），默认关待真实 trace | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 19 | 2026-07-03 | M8 博弈投影层 P3 §6.3 鲜度/资源 race（默认关） | `decision.py` 两子能力各带开关：**鲜度 race** `_losing_freshness_race`（`ENABLE_FRESHNESS_RACE`；对手鲜度−我方鲜度 ≥ `FRESHNESS_RACE_GAP`(10) 视为劣势）→ `_freshness_rescue(world, me)` 把冰鉴使用阈值从 `ICE_BOX_USE_BELOW`(78) 抬到 `ICE_BOX_RACE_USE_BELOW`(88)，劣势时提前保阈值（不为省资源致好果转坏）；**资源 race** `_maybe_resource_race`（`ENABLE_RESOURCE_DENY`）用 §6.1 `opponent_eta.eta(node)` 抢占对手争夺(ETA 有限)、我方到该点帧数 ≤ 对手 ETA+`RESOURCE_DENY_ETA_MARGIN`(抢得到)、库存有限、额外帧 ≤ `RESOURCE_RACE_MAX_EXTRA_FRAMES`(20,不显著偏离)、过 `_can_afford`、未囤够 `RESOURCE_RACE_ICEBOX_KEEP`(2) 的路线附近冰鉴节点，选对手最快到达者；`_maybe_claim` 冰鉴保有量在开关开时抬到 race 值以便到点领取。`_plan` race 绕路顺序：任务 deny→资源争夺→任务追平/绕路。config 增 5 项 §6.3 常量。新增 `test_freshness_resource_race.py` 12 项（鲜度劣势提前用/相近不提前/常态阈值内仍用/无冰鉴/开关关；资源抢占/对手不可达/抢不过/已足额/开关关）共 +12（合计 214）全通过；四开关默认关故 mock 零回归 @r48 | 鲜度阈值博弈：劣势提前保、抢占对手争夺的冰鉴；均默认关待真实 trace | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 18 | 2026-07-03 | M8 博弈投影层 P3 §6.2 任务 race（默认关） | `decision.py` 两子能力各带开关：**追平** `_task_catch_up_active`（`ENABLE_TASK_RACE`；对手任务分≥`TASK_RACE_OPP_THRESHOLD`=80 且我方<90 时，`_task_detour_target` 把 seek_target 抬到≥90、绕路上限抬到 AGGRESSIVE，仍过 `_can_afford`+档位 ΔEV 地板）；**Deny** `_task_deny_target`（`ENABLE_TASK_DENY`；遍历可领取任务，用 §6.1 `opponent_eta.eta(node)` 判对手正奔赴、我方到该点帧数 ≤ 对手 ETA+`TASK_DENY_ETA_MARGIN`(不跑空趟)、`_crosses_milestone`(60/90/110) 判抢占阻其里程碑，过 `_can_afford`+`_detour_net_delta≥0`，选对手 ETA 最早者）。`_plan` 中 deny 优先于常规绕路。config 增 `ENABLE_TASK_RACE`/`TASK_RACE_OPP_THRESHOLD`/`TASK_DENY_ETA_MARGIN`。新增 `test_task_race.py` 14 项（追平覆盖 CONSERVATIVE/阈值/自身达标/开关；Deny 抢占/对手不可达/无里程碑/抢不过/被保护/开关/`_crosses_milestone`）共 +14（合计 202）全通过；两开关默认关故 mock 零回归 @r48 | 任务分 race：落后补差(边际高值)、抢占阻断对手里程碑；均默认关待真实 trace 验证 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 17 | 2026-07-03 | M8 博弈投影层 P3 §6.1 对手轨迹 ETA（纯观测） | `projection.py` 新增 `OpponentEta`(from_node/to_gate/to_finish/to_nodes/verified/confidence + `eta(node)`) 与 `Projector.build_opponent_eta(world)`：以对手 `current_node_id`/`next_node_id`/`move_progress`/`verified` 估算到宫门/终点/活跃任务点/有货资源点的帧数——在途(0<progress<1)以 next_node 起算并加到 next 的残余帧(`_eta_base`)，未验核 to_finish 计 `_verify_frames`；`_eta_targets` 收集任务/资源节点；`_eta_confidence` 随终局上升、按 `_track_opp_route`(原地改目标=路线变更)计数打折。`Projector` 增 `_opp_prev`/`_opp_route_changes` 跨帧状态。`decision.py` 每帧 `_update_projection` 构建存 `self.opponent_eta`、**不改任何动作**；`main.py` 每帧输出 `Eta` trace。新增 `test_opponent_eta.py` 8 项（在节点/在途 ETA、未验核加验核、任务·资源 ETA、无对手降级、置信随回合升、轨迹变化降置信、接入 decide 不改动作）共 +8（合计 188）全通过；mock 对手静止故 ETA 恒定、零回归 @r48 | 对手轨迹 ETA 成为只读争夺判断输入，为 §6.2/§6.3 race 铺路 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 16 | 2026-07-03 | M8 博弈投影层 P2 突破烧好果意愿（§5.1 行3）接入决策——**P2 全部完成** | `decision.py` `_breakthrough` 增 CONSERVATIVE 保好果分支：新增 `_prefer_forced_pass`（仅 `tuning.protect_good_fruit_on_breakthrough` 且 `_forced_pass_tax` 过 `_can_afford` 时返 True）+ `_forced_pass_tax`（障碍固定税 `OBSTACLE_TIME_TAX`；敌卡按节点类型 key_pass/gate/normal + 防守值走 `rules.guard_time_tax`）。CONSERVATIVE 领先且时间税可负担 → 障碍/敌卡突破优先 `FORCED_PASS`（不烧好果）；负担不起 → 回退 `CLEAR`/`BREAK_GUARD`（烧好果保交付）。EVEN/AGGRESSIVE 维持烧好果攻坚。`tuning.py` `StrategyTuning` 增 `protect_good_fruit_on_breakthrough`（CONSERVATIVE True）；`decision.py` 引入 `from core import rules`。新增 `test_breakthrough_fruit.py` 10 项（三档障碍/敌卡分支、时间紧回退 CLEAR、时间税估算、档位映射）共 +10（合计 180）全通过；mock EVEN 故零回归 @r48（obstacle 仍 SQUAD_CLEAR/CLEAR） | 必要突破前提下按档位在"烧好果快过"与"付时间保好果"间取舍，且绝不因保好果而误交付 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 15 | 2026-07-03 | M8 博弈投影层 P2 窗口 EV（§5.4 + §5.1 行5）接入决策 | `decision.py` 重构 `_window_card` 为**代价感知 + 档位门控**：依 §5.4.3 成本口径把牌分两类——无代价牌(兵争=行动点、验牒=文书[无其它主动用途]、免费强行=已有马/疾行 buff，均不减交付分/不拖交付时间)按克制强度 兵争>验牒>免费强行 恒出(弱优于弃权)；献贡(消耗 1 好果=直接减交付好果分，唯一有交付代价的牌)仅**非 CONSERVATIVE** 且窗口价值明显(`WINDOW_VALUABLE_CONTEST_TYPES`=TASK/GATE/PASS/DOCK)、好果 > 档位下限(`WINDOW_XIANGONG_MIN_GOOD_EVEN`=50/`_AGGRESSIVE`=12)、鲜度≥80 时出；**不为窗口烧马**(强行消耗马那支删除——马用于交付提速价值更高)；CONSERVATIVE 只出无代价牌否则弃权。新增 `test_window_ev.py` 14 项（无代价牌优先级/CONSERVATIVE 不烧好果/EVEN·AGGRESSIVE 好果下限差异/低价值窗口不烧/鲜度<80 不可献贡/不烧马/无窗口 None）共 +14（合计 170）全通过；mock 无窗口故零回归 @r48。**P2 至此仅剩 §5.1 行3** | 窗口出牌从"出第一张可出牌"升级为代价感知+档位门控，锁住交付好果不被窗口无谓消耗 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 14 | 2026-07-03 | M8 博弈投影层 P2 终局交付 race（§5.3）接入决策 | `decision.py` 新增 `_endgame_race_state(world, me)`（RUSH 相位 + 对手投影 deliver_frame 与我方 deliver_frame 均在 `ENDGAME_RACE_WINDOW`(20) 帧内 → racing；`gap≤0` → behind）；`_rush_speed_warranted` 改为 race-aware：race 且落后/接近 → 放宽"远离终点"门槛用 `RUSH_SPEED` 抢交付帧，race 且领先 → 抑制疾行(不烧 +25% 鲜度，留急策护果)；鲜度危急/持马仍不疾行；非 race 维持原门槛。领先且鲜度临界的 `RUSH_PROTECT` 由既有 `_maybe_rush_protect` 覆盖。新增 `test_endgame_race.py` 11 项（落后近处抢帧/非race近处不冲/领先抑制/非race远处保持原疾行/鲜度危急不冲/持马不冲 + `_endgame_race_state` 各分支）共 +11（合计 156）全通过；mock 无对手推进/悬赏故零回归 @r48 | 终局据对手投影分差在"抢交付帧"与"锁交付质量"间取舍 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 13 | 2026-07-03 | M8 博弈投影层 P2 悬赏机会主义（§5.2）接入决策 | `decision.py` 新增 `_maybe_bounty`（在 `_plan` 的 opportunistic 之后、set_guard 之前）：遍历 `world.bounties`，对**对手有效设卡**且 `_plan_attack` 低成本可破的悬赏节点，计算绕开其它阻塞后的额外帧（`≤BOUNTY_MAX_EXTRA_FRAMES=25`）、过 `_can_afford` 与 `net_score_delta≥BOUNTY_MIN_NET_SCORE=15`（悬赏原始分作 `extra_bounty`，烧好果作 `good_fruit_burned`，额外耗时/鲜度计入）；相邻→`BREAK_GUARD`(最小投入,保好果下限)，否则沿路径 `MOVE` 靠近一步。CONSERVATIVE(锁胜)/RUSH(保交付) 不追悬赏。新增 `test_bounty_opportunism.py` 10 项（破卡/靠近/高防守·自方卡·远绕路·零收益·已完成跳过/CONSERVATIVE·RUSH 不追）共 +10（合计 145）全通过；mock 无悬赏数据故 `_maybe_bounty` 不触发、仍 @r48 交付零回归 | 破关悬赏成为顺路正 EV 收益来源，受 ΔEV 地板与档位/相位守卫保护交付下限 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 12 | 2026-07-03 | M8 博弈投影层 P2 档位调参接入决策 | `decision.py` 每帧 `tuning_for_mode(mode)` 刷新 `StrategyTuning`：①`_task_detour_target` 用档位 `task_seek_target`/`task_detour_max_extra_frames`，并新增 §3.3 ΔEV 地板守卫（`_detour_net_delta` 以本方投影为基线、计入额外耗时+鲜度损耗，读任务 `score` 作任务分增量；`< 档位阈值` 则拒绝绕路）；②`_maybe_rush_protect`/`_rush_speed_warranted` 改用档位护果令阈值。`tuning.py` `StrategyTuning` 增 `rush_protect_freshness_below`（CONSERVATIVE/EVEN=90、AGGRESSIVE=75）；`config.py` 增 `AGGRESSIVE_RUSH_PROTECT_FRESHNESS_BELOW=75`。新增 `test_mode_tuning_wiring.py`（三档绕路差异/AGGRESSIVE 放宽上限/ΔEV 拒低价值绕路且 AGGRESSIVE 也不放净负分/护果令时机）+ 扩 tuning 单测，共 +9（合计 135）全通过；mock 端到端仍 @r48 交付（mode 恒 EVEN=既有默认，零回归） | gap 驱动的档位参数正式改变动作（EVEN 之外档位切换时），且受 ΔEV 地板保护不做净负分绕路 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 11 | 2026-07-03 | M8 博弈投影层 P1+P1.5 落地（纯观测，不改动作） | 新增 `strategy/projection.py`：①`Projector` 每帧投影双方终局分/交付帧→gap→`ModeMachine`(滞后+低置信回落 EVEN)，产出只读 `ProjectionBus`；②`project_final_score` 复用 `core/rules.py` 组合投影分；③`net_score_delta`（§3.3 分数质量地板）纯函数估算增量动作 ΔEV。新增 `strategy/tuning.py` `tuning_for_mode`（Layer 2 档位参数，EVEN=既有默认，尚未被消费）。`decision.py` 每帧构建投影总线（异常安全、**不改任何动作**）；`main.py` 输出 `Projection`/`ModeChange` trace。`config.py` 增 §9 常量（LEAD_SAFE/滞后/置信阈值/ΔEV 三档/进取绕路上限 90/悬赏/子能力开关）。新增 4 个测试文件 30 项单测（共 126）全通过；mock 端到端仍 @r48 交付、动作逐帧一致，Projection trace 每帧输出、confidence 前段<0.55 故 mode 恒 EVEN（符合设计） | `world.opponent` 成为投影总线一等输入（纯观测）；分数质量地板与档位参数基础设施就绪，供 P2-P4 校准后接入 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
| Iteration 10 | 2026-07-03 | 博弈投影层设计评审与优化（未改运行期代码） | 依据代码/协议核对 `docs/game_theory_projection_strategy.md`：①**修正时序前提**——mock ~r48–r55 交付不代表实战，真实交付在 450+，据此确认存在约 450 帧争夺中局、上调 Layer 3/4 价值评估；②**新增分数质量地板 §3.3**（`ΔEV≥0`）——补 `_can_afford` 只守时间不守分数的缺口，防 AGGRESSIVE 重演 839cfc9 过度贪任务/烧好果；③AGGRESSIVE 绕路上限从直觉 120 收敛到 90；④明确投影 confidence 前段低、mode 主战场在中后段；⑤落地顺序改为 P1 纯观测先行 + P1.5 ΔEV 地板前置于任何改动作层。同步 AGENTS 能力矩阵（新增博弈层行）/Roadmap（M8）/已知限制 | 博弈层设计定稿、与历史败局教训对齐；实现前的规格就绪 | `CHANGELOG.md`、`docs/game_theory_projection_strategy.md` |
