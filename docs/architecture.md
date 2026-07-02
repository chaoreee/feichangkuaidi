# 架构设计（architecture.md）

本文件是 `AGENTS.md` 的架构落档版，描述系统分层、模块职责、数据流、关键技术决策与 Roadmap。规则细节以任务书/协议为准，本文件不重复规则。

## 1. 分层与运行/开发分离

```
┌──────────────────────────────────────────────────────────────┐
│  能力基线：AGENTS.md（SSOT） + docs/（spec/protocol/task/arch） │
└───────────────┬─────────────────────────┬────────────────────┘
                ▼                          ▼
   运行期  client/（提交平台，纯 stdlib）   开发期  analysis/（赛后离线）
   communication→protocol→core→strategy    parser→evaluator→optimizer→report
        └─────── logger → logs/ ───────────────────►（日志驱动分析）
                └───── 迭代闭环：分析结论回写 client / 基线 ─────┘
```

**核心原则**：`client/` 内**不得**出现分析代码或第三方依赖；提交包只含运行期所需，纯标准库、离线可跑。

## 2. 运行期 Client 模块职责

| 模块 | 职责 | 关键点 |
|---|---|---|
| `communication/` | TCP 长连接、收发、拆帧、缓冲、超时兜底 | 阻塞 socket + 双线程（见 §4 决策）；按 5 位长度前缀拆帧 |
| `protocol/` | 消息 DTO 编解码、动作构造、枚举常量 | 字段名大小写敏感；空动作心跳 `actions: []` |
| `core/` | 游戏状态镜像 `WorldState` + 规则计算 + 寻路 | 无副作用查询接口；供 strategy 使用 |
| `strategy/` | 决策：输入 WorldState，输出 `List[Action]` | **不 import socket**；分层：路线→资源/任务→对抗→终局 |
| `logger/` | 结构化 JSONL 日志旁路记录 | 文件名含 matchId；供赛后分析 |
| `config.py` `main.py` | 参数/超时/开关；组装启动闭环 | argv=`playerId host port`，禁止写死 |

## 3. 数据流与模块协作

```
平台 ⇄ communication ⇄ protocol ⇄ core(WorldState) → strategy → protocol → communication ⇄ 平台
                                       │
                                    logger → logs/match_xxx/runtime.jsonl
                                                     │（赛后离线）
                           parser → evaluator → optimizer → report → logs/match_xxx/analysis.md
                                                     │
                        回写 → AGENTS.md / CHANGELOG.md / docs/delivery_spec.md / client/
```

单帧主循环（M1 目标）：
```
收到 inquire(N)
  → protocol 解析 → core 更新 WorldState
  → strategy.decide(world) → List[Action]（含硬超时，超时降级为 [] / WAIT）
  → protocol 构造 action(round=N) → communication 发送
  → logger 记录本帧收/发/决策依据/耗时
收到 over → 记录最终分 → 退出
```

## 4. 关键技术决策

| 决策 | 选型 | 理由 |
|---|---|---|
| 语言/依赖 | Python 3.12.9，纯标准库 | 任务书 §10.5 禁止现场安装第三方依赖；stdlib 足够（socket/json/threading/dataclasses） |
| **IO 模型** | **阻塞 socket + 双线程**（接收线程拆帧入队，主线程决策发送） | 契合严格回合请求-响应节奏，实现直观、易调试、超时兜底简单（Iteration 0 决定） |
| 状态表示 | 强类型 `WorldState`（dataclass），每帧由 inquire 重建 | 与协议字段解耦策略，便于离线回放测试 |
| 寻路 | Dijkstra，边权 = 到站所需移动量 `ceil(distance × 路线耗时系数)` | 任务书 §2.3.2；单向边只按方向 |
| 健壮性 | 任何异常/超时都发出合法心跳（空 actions） | 连续 60 帧缺动作即退赛，代价最大，必须避免 |
| 测试 | stdlib `unittest` + `scripts/mock_server.py` 本地假服务端 | 无网络也能回归拆帧/寻路/规则/策略 |

## 4b. 参考样例 samples/

`samples/` 存放参考样例，作为 **规格参考 + M2 解析开发依据 + 离线测试夹具**（供 `scripts/mock_server.py`、`client/tests/` 加载）。
- `map_config.json`（✅ 已提供）：中等难度竞技地图原始配置，是 `start` 载荷的子集（缺 `edgeId`/`bidirectional`/`count`/`claimRound`/英文 `processType`/`canWindow`/`taskTemplates`/`gameplay`）。
- `start_message.json` / `inquire_message.json`（⛔ 暂不提供）：其结构以 **通信协议 §5 / §7 + 附录 B/C/D/F** 与 `docs/protocol.md` 为准。

样例为只读快照，运行期不被 `client/` import；策略禁止硬编码其中的节点/路线/资源位置。字段差异与结构详见 `samples/README.md`。

## 5. 交付工程

- `start.sh` 位于仓库根/ZIP 根，可执行，接收 `playerId host port` 并透传给 `client/main.py`。
- `scripts/build_zip.sh` 打包 ZIP：根目录直接含 `start.sh`，不套同名目录；执行 §10.7 自检。
- 运行时不联网、不安装、不写系统目录。

## 6. Roadmap（里程碑）

| 里程碑 | 交付 | 验收 |
|---|---|---|
| M0 | 文档基线 + 目录骨架 | 本轮 |
| M1 | framing + TCP 双线程 + 消息 DTO + logger + mock_server + start.sh | 对 mock_server 跑通 registration→over 空跑，全程合法心跳，不退赛 |
| M2 | WorldState 解析 + 地图/寻路 + 规则公式 + 单测 | 单测通过；能从录制日志重建状态 |
| M3 | 基线策略（最短路→处理→验核→交付） | mock 对局能稳定交付并得分 |
| M4 | 资源/任务/鲜度收益策略 | 交付分 + 任务分显著提升 |
| M5 | 对抗（设卡/攻坚/强制通行/窗口/小分队/急策） | 对抗动作合法生效、无非法动作扣分 |
| M6 | analysis 四件套 + 首份 analysis.md + 回写基线 | 闭环跑通 |
| M7+ | 真实对局日志驱动迭代 | 持续 |
