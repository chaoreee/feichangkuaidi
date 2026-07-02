# CHANGELOG

本文件记录每轮迭代的能力变化。格式：轮次 / 日期 / 变更摘要。能力矩阵与迭代明细见 `AGENTS.md`。

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
