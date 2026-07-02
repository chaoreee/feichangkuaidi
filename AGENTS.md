# AGENTS.md — 项目能力基线（Single Source of Truth）

> 本文件是《一骑红尘：荔枝争运战》Agent 交付件开发系统的**唯一能力基线**。
> 所有开发以本文件为依据；每次能力发生变化时**必须同步更新**本文件的"能力矩阵"与"迭代日志"。

- 最后更新：2026-07-02
- 当前轮次：Iteration 7（M7 能力补全）
- 规则来源：`一骑红尘：荔枝争运战 参赛选手任务书.md`、`一骑红尘：荔枝争运战 通信协议.md`（二者为最高权威，本文件与其冲突时以原始文档为准）

---

## 1. 项目目标与胜负口径

- **目标**：交付一个可提交比赛平台的 Python 客户端（Client），并建立"日志→分析→优化→更新基线"的持续迭代闭环。
- **局内胜负**（任务书 §1.3 / §7）：比赛结束时最终总分高者胜；总分相同直接判平。最终总分 = 送达基础分 + 皇榜任务分 + 用时分 + 好果数量分 + 鲜度品质分 + 破关悬赏分 − 惩罚，最低计 0。
- **平台积分**（任务书 §9）：正常参赛比总分（胜 3 / 负 0）；平分决胜按 鲜度→好果→惩罚 顺序。**未交付则送达/好果/鲜度/用时四项全为 0**，任务分封顶 80、悬赏封顶 25 —— 故"稳定交付"是第一优先。

## 2. 当前系统架构

四层：能力基线（本文件 + docs/）→ 运行期 Client（`client/`，纯 stdlib、可提交、离线可跑）→ 开发期分析（`analysis/`，赛后离线）→ 迭代闭环。
运行期与开发期严格分离：`client/` 内不含任何分析代码，保证提交包纯净。数据流与模块协作见 `docs/architecture.md`。
`samples/` 存放参考样例：`map_config.json`（✅ 已提供，中等难度竞技地图原始配置，为 `start` 载荷子集）；`start_message.json`/`inquire_message.json`（⛔ 暂不提供，结构以通信协议 §5/§7 + `docs/protocol.md` 为准）。只读，不被 `client/` import。字段差异详见 `samples/README.md`。

## 3. Agent 职责与工作原则

1. AGENTS.md 是唯一能力基线（SSOT）。
2. 所有代码实现严格遵循 `docs/delivery_spec.md`。
3. 所有实现严格符合任务书与通信协议。
4. 每场比赛日志独立保存于 `logs/match_xxx/`，可追溯。
5. 每轮日志分析输出完整 `analysis.md`。
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
| 皇榜任务取舍（机会式 + 预算内绕路）+ 鲜度管理 | ✅ | 目标即当前节点直接做；任务分<90 且预算允许时向近处任务节点绕路；时间预算守卫保证仍能交付 |
| 阻塞感知路由（障碍/敌卡绕行） | ✅ | `time_optimal_path(blocked=...)`；仿真中障碍不可绕行时突破 |
| 突破：障碍→T04/CLEAR/强制通行 + 绕行/清障代价权衡 | ✅ | `_breakthrough`；绕行远超就地清障成本时改为清障；保留最低好果 |
| 突破：敌方设卡→攻坚破卡(含破关令)/强制通行 | ✅ | `_plan_attack` 最小投入达防守值，RUSH 绑破关令+3；不够则强制通行；单测覆盖 |
| 窗口出牌（响应本方窗口） | ✅ | `_window_card` 按可支付牌(兵争/献贡/验牒/强行)否则弃权 |
| 终局急策 疾行令/护果令（二选一）+ 破关令 | ✅ | 低鲜度护果令、畅通且远且无马用疾行令、攻坚绑破关令 |
| 小分队探路宫门（减验核 3 帧） | ✅ | `_maybe_squad`；仿真验核 6→3 帧 |
| 防御性小分队：预清路线障碍(SQUAD_CLEAR)/削弱前方敌卡(SQUAD_WEAKEN) | ✅ | 阻塞在路径第 2 跳后由小分队预处理；仿真 SQUAD_CLEAR 提前清障，主车队免耗好果(交付好果 100) |
| 主动设卡(SET_GUARD)/增援等进攻干扰 | 🟡 | 已实现关键关隘设卡逻辑，`config.ENABLE_OFFENSIVE` 默认关闭（delivery-first，占用己方交付时间）；单测覆盖开/关 |

### 4.4 日志与分析
| 能力 | 状态 | 备注 |
|---|---|---|
| 结构化 JSONL 运行日志（收包/发包/决策/状态/耗时/异常/每帧状态与事件） | ✅ | `logger/match_logger.py` + main `frame` 记录；`logs/match_{matchId}_{playerId}.jsonl` |
| parser / evaluator / optimizer / report 四件套 | ✅ | `analysis/`；`python -m analysis <log>` 产出 `analysis.md`；真实日志验证；5 项单测 |

### 4.5 交付工程
| 能力 | 状态 | 备注 |
|---|---|---|
| start.sh（`./start.sh <playerId> <host> <port>`，可执行） | ✅ | 根目录，LF、+x，透传参数给 `client/main.py` |
| ZIP 打包脚本 + §10.7 自检清单 | ✅ | `scripts/build_zip.py`(+`.sh`)；ZIP 根含可执行 start.sh + client/；自检全 PASS(纯 stdlib/无安装/无硬编码 IP) |
| 纯 stdlib、离线、无现场安装 | ✅ | 零第三方依赖，仅 socket/json/threading/queue |

## 5. 当前问题与已知限制

- 无法访问比赛内网运行环境，只能靠导出日志离线分析（任务书 §4 要求）。
- 当前协议不承诺断线重连；连接需稳定，异常需记录，但不强求恢复对局。
- 单帧决策建议 500ms 内完成，策略需轻量并设硬超时降级。
- 地图为变体、局内固定：一切节点/路线/资源/任务候选点/障碍候选点必须从 `start` 动态读取，禁止硬编码（协议附录 A 明确警告）。
- 进攻干扰（主动设卡/增援）默认关闭（`config.ENABLE_OFFENSIVE`）：delivery-first，未验证其对总分的正收益；如需启用需配真实对局数据调参。
- 情报(INTEL)仅在"前方处理点的入边距离≤15"时领取/使用；当前竞技地图各边距离均>15，故该图上情报不生效（属地图特性，非缺陷）。
- 拒绝反馈基于上一帧 actionResults/events；对连续新型阻塞采用"临时拉黑目标+绕行"，不保证在所有极端拓扑下最优，但避免死循环。

## 6. 后续规划（Roadmap）

M0 文档基线（本轮，✅ 交付中）→ M1 通信打通 → M2 核心镜像 → M3 基线策略（稳定交付）→ M4 收益策略 → M5 对抗策略 → M6 分析闭环 → M7+ 按真实日志迭代。里程碑详情见 `docs/architecture.md` §Roadmap。

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
