# AGENTS.md — 项目能力基线（Single Source of Truth）

> 本文件是《一骑红尘：荔枝争运战》Agent 交付件开发系统的**唯一能力基线**。
> 所有开发以本文件为依据；每次能力发生变化时**必须同步更新**本文件的"能力矩阵"与"迭代日志"。

- 最后更新：2026-07-02
- 当前轮次：Iteration 1（M1 通信打通）
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
| 错误码处理（协议 §11 全量） | 🟡 | 立即 error 已记录并继续；分类处置待 M2 |

### 4.2 核心状态与规则镜像（core）
| 能力 | 状态 | 备注 |
|---|---|---|
| WorldState 解析（players/nodes/edges/tasks/contests/weather/events） | ❌ | M2 |
| 地图与寻路（Dijkstra，边权=到站移动量） | ❌ | M2 |
| 规则公式镜像（移动/鲜度/时间税/得分/悬赏） | ❌ | M2，任务书 §2.3/§3.2/§6/§7 |

### 4.3 策略（strategy，与通信解耦）
| 能力 | 状态 | 备注 |
|---|---|---|
| 基线推进（最短路→站点处理→宫门验核→交付） | ❌ | M3 |
| 资源领取与使用（冰鉴/马/情报/护果令） | ❌ | M4 |
| 皇榜任务取舍 + 鲜度管理 | ❌ | M4 |
| 对抗（设卡/攻坚/强制通行/窗口出牌/小分队） | ❌ | M5 |
| 终局急策（疾行令/护果令/破关令） | ❌ | M5 |

### 4.4 日志与分析
| 能力 | 状态 | 备注 |
|---|---|---|
| 结构化 JSONL 运行日志（收包/发包/决策/状态/耗时/异常） | ✅ | `logger/match_logger.py`；`logs/match_{matchId}_{playerId}.jsonl` |
| parser / evaluator / optimizer / report 四件套 | ❌ | M6 |

### 4.5 交付工程
| 能力 | 状态 | 备注 |
|---|---|---|
| start.sh（`./start.sh <playerId> <host> <port>`，可执行） | ✅ | 根目录，LF、+x，透传参数给 `client/main.py` |
| ZIP 打包脚本 + §10.7 自检清单 | ❌ | M6（`scripts/build_zip.sh`） |
| 纯 stdlib、离线、无现场安装 | ✅ | 零第三方依赖，仅 socket/json/threading/queue |

## 5. 当前问题与已知限制

- 无法访问比赛内网运行环境，只能靠导出日志离线分析（任务书 §4 要求）。
- 当前协议不承诺断线重连；连接需稳定，异常需记录，但不强求恢复对局。
- 单帧决策建议 500ms 内完成，策略需轻量并设硬超时降级。
- 地图为变体、局内固定：一切节点/路线/资源/任务候选点/障碍候选点必须从 `start` 动态读取，禁止硬编码（协议附录 A 明确警告）。

## 6. 后续规划（Roadmap）

M0 文档基线（本轮，✅ 交付中）→ M1 通信打通 → M2 核心镜像 → M3 基线策略（稳定交付）→ M4 收益策略 → M5 对抗策略 → M6 分析闭环 → M7+ 按真实日志迭代。里程碑详情见 `docs/architecture.md` §Roadmap。

## 7. 迭代日志

| 轮次 | 日期 | 触发 | 主要改动 | 能力增量 | 关联 |
|---|---|---|---|---|---|
| Iteration 0 | 2026-07-02 | 项目初始化 | 建立 AGENTS.md、docs/（architecture/delivery_spec/protocol/task）、CHANGELOG、目录骨架；确定 IO 模型=阻塞 socket+双线程 | 文档基线成型 | `CHANGELOG.md` |
| Iteration 1 | 2026-07-02 | M1 通信打通 | 实现 framing/enums/messages/actions、双线程 TcpClient、JSONL logger、占位 DecisionEngine、config、main 启动闭环、start.sh、mock_server、framing 单测；端到端跑通 registration→over，全程空动作心跳不退赛 | 通信层可用 | `CHANGELOG.md` |
