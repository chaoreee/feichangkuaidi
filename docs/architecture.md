# 架构设计（architecture.md）

本文件是 `CLAUDE.md` 的架构落档版，描述系统分层、模块职责、数据流、关键技术决策与 Roadmap。规则细节以任务书/协议为准，本文件不重复规则。

## 1. 分层与运行/开发分离

```
┌──────────────────────────────────────────────────────────────┐
│  能力基线：CLAUDE.md（SSOT） + docs/（spec/protocol/task/arch） │
└───────────────┬──────────────────────────────────────────────┘
                ▼
   运行期  client/（= 提交平台的交付件根目录，纯 stdlib、离线可跑，**只记日志不做分析**）
   communication → protocol → core → strategy
        └── logger → client/logs/match_*.log（人类可读 trace，含 Rejected/CanAffordBlock 内部信号）
                          │ 对战后随交付件下载回本地
                          ▼
   采集   logs/（client 之外）：取回的 trace 入库（logs/real/ 平台、logs/sim/<variant>/ 仿真）
                          │ analysis/（仓库根，client 之外）parser 解析 trace → Report + aggregator 聚合
                          ▼
   分析报告 docs/analysis_report.md（5-10KB，跨局对比 + 异常局标记）+ docs/ab_report.md
                          │ Claude Code 读聚合报告做归因（不直读 10w 字 trace）
                          ▼
   迭代闭环：结论回写 client / CLAUDE.md / CHANGELOG.md
```

**核心原则**：`client/` **本身即交付件根目录**——手动打包时，`client/` 内容直接构成 ZIP 根（`start.sh`、`main.py`、各子包同级）。包内不得出现第三方依赖；纯标准库、离线可跑、**只记 trace 日志**。**分析器在 client 之外**（仓库根 `analysis/`）：对局结束后把取回的 trace 事后解析为结构化 `Report`，再跨局聚合产出报告，Claude Code 读报告做归因——**代码抽取事实、AI 只做解释**，分析器不做优化（Iteration 9 删旧 `analysis/` 后以正确形态回归，详见 `docs/iteration_plan_v2.md`）。

## 2. 运行期 Client 模块职责

| 模块 | 职责 | 关键点 |
|---|---|---|
| `communication/` | TCP 长连接、收发、拆帧、缓冲、超时兜底 | 阻塞 socket + 双线程（见 §4 决策）；按 5 位长度前缀拆帧 |
| `protocol/` | 消息 DTO 编解码、动作构造、枚举常量 | 字段名大小写敏感；空动作心跳 `actions: []` |
| `core/` | 游戏状态镜像 `WorldState` + 规则计算 + 寻路 | 无副作用查询接口；供 strategy 使用 |
| `strategy/` | 决策：输入 WorldState，输出 `List[Action]` | **不 import socket**；分层：路线→资源/任务→对抗→终局；经 `trace_events` 暴露被拒/拦截信号供 main 落盘 |
| `logger/` | 人类可读 trace 日志旁路记录 | 写 `client/logs/match_<matchId>_<playerId>.log`；每行一事件，逐行 flush；含 `Rejected`/`CanAffordBlock` 内部信号行 |
| `config.py` `main.py` | 参数/超时/开关；组装启动闭环 | argv=`playerId host port`，禁止写死；`start.sh` 与 `main.py` 同级（包内） |

> **client 不含分析模块**。赛后分析由仓库根 `analysis/`（client 之外）承担：`parser.parse_log` 把 `match_*.log` 解析为 `Report`（schemaVersion=1），`aggregator` 跨局聚合，CLI `python3 -m analysis`。详见 `docs/iteration_plan_v2.md` §3。

## 3. 数据流与模块协作

```
平台 ⇄ communication ⇄ protocol ⇄ core(WorldState) → strategy → protocol → communication ⇄ 平台
                                       │
                                    logger → client/logs/match_<matchId>_<playerId>.log（人类可读 trace）
                                       │（对战后随交付件下载回本地）
                          复制到仓库 logs/（client 之外）
                                       │ analysis/parser.parse_log 解析 trace → Report（schemaVersion=1）
                                       │ analysis/aggregator 聚合（跨局统计 + seed 配对 A/B + 异常局标记 + rules.py 对账）
                                       ▼
                          docs/analysis_report.md（5-10KB，AI 消费的主文档）+ docs/ab_report.md
                                       │ Claude Code 读聚合报告 + 被标记单局 Report 做归因
                        回写 → CLAUDE.md / CHANGELOG.md / docs/delivery_spec.md / client/
```

单帧主循环：
```
收到 inquire(N)
  → protocol 解析 → core 更新 WorldState
  → strategy.decide(world) → List[Action]（含硬超时，超时降级为 [] / WAIT）
       └─ decision 经 trace_events 暴露被拒/canAfford 拦截信号
  → protocol 构造 action(round=N) → communication 发送
  → logger 写 Frame + Action trace（超预算才附 ms）+ Rejected/CanAffordBlock 内部信号行
收到 over → 写 Over / Score trace → 退出
（trace 随交付件下载回本地后，由仓库侧 analysis/ 解析聚合）
```

## 4. 关键技术决策

| 决策 | 选型 | 理由 |
|---|---|---|
| 语言/依赖 | Python 3.12.9，纯标准库 | 任务书 §10.5 禁止现场安装第三方依赖；stdlib 足够（socket/json/threading/dataclasses） |
| **IO 模型** | **阻塞 socket + 双线程**（接收线程拆帧入队，主线程决策发送） | 契合严格回合请求-响应节奏，实现直观、易调试、超时兜底简单（Iteration 0 决定） |
| 状态表示 | 强类型 `WorldState`（dataclass），每帧由 inquire 重建 | 与协议字段解耦策略，便于离线回放测试 |
| 寻路 | Dijkstra，边权 = 到站所需移动量 `ceil(distance × 路线耗时系数)` | 任务书 §2.3.2；单向边只按方向 |
| 健壮性 | 任何异常/超时都发出合法心跳（空 actions） | 连续 60 帧缺动作即退赛，代价最大，必须避免 |
| 测试 | stdlib `unittest` + `scripts/mock_server.py` 本地假服务端；Iter 21+ 规划 `scripts/sim_server.py` 高保真自博弈仿真（物理复用 `core/rules.py`） | 无网络也能回归拆帧/寻路/规则/策略；仿真器提供 A/B 证据（见 `iteration_plan_v2.md` Phase A） |

## 4b. 参考样例 samples/

`samples/` 存放参考样例，作为 **规格参考 + M2 解析开发依据 + 离线测试夹具**（供 `scripts/mock_server.py`、`client/tests/` 加载）。
- `map_config.json`（✅ 已提供）：中等难度竞技地图原始配置，是 `start` 载荷的子集（缺 `edgeId`/`bidirectional`/`count`/`claimRound`/英文 `processType`/`canWindow`/`taskTemplates`/`gameplay`）。
- `start_message.json` / `inquire_message.json`（⛔ 暂不提供）：其结构以 **通信协议 §5 / §7 + 附录 B/C/D/F** 与 `docs/protocol.md` 为准。

样例为只读快照，运行期不被 `client/` import；策略禁止硬编码其中的节点/路线/资源位置。字段差异与结构详见 `samples/README.md`。

## 5. 交付工程

- `client/` 本身即交付件根目录。`client/start.sh` 与 `main.py` 同级，可执行，接收 `playerId host port` 并透传给同目录 `main.py`（`start.sh` 内**不含中文**）。
- **打包由人工完成**：把 `client/` 的**内容**打成 ZIP（`start.sh` 直接位于 ZIP 根，不多套一层目录）。仓库内不再保留打包脚本。打包前建议剔除 `__pycache__/`、`logs/*.log` 等运行期产物。
- 提交前对照任务书 §10.7 自查：ZIP 根含可执行 `start.sh`、接收 3 参数、纯标准库、无现场安装、无硬编码 IP。
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
| M6 | 分析闭环 + 回写基线 | 闭环跑通 |
| M7+ | 真实对局日志驱动迭代 | 持续 |
| M8 | 博弈投影层 P1-P4 代码落地（详见 `game_theory_projection_strategy.md`） | mock 零回归；阈值/开关待校准 |
| M9 | **分析器驱动证据型迭代**（Iteration 21 起，进行中）：in-client 采集器 + repo 聚合器 + 高保真仿真器 + 静态规划器 + 仿真校准 + 博弈层重排 | 详见 `docs/iteration_plan_v2.md`；新"done"标准须过仿真 A/B 证据 |
