# samples/ — 协议与地图参考样例（reference fixtures）

本目录存放比赛的 **参考样例**，用作：规格核对、M2 `core.WorldState` 解析与寻路的开发依据、以及离线测试夹具。

> 这些是 **只读参考快照**，不是运行时权威。正式对战一切以服务端本局 `start` / 每帧 `inquire` 实际下发为准；
> 策略**禁止**硬编码这里的节点/路线/资源/任务位置（协议附录 A 明确要求）。样例文件不被 `client/` import，保证提交包纯净。

## 文件清单

| 文件 | 状态 | 内容 / 参考 |
|---|---|---|
| `map_config.json` | ✅ 已提供 | 中等难度竞技地图**原始配置**（见下方结构说明） |
| `start_message.json` | ⛔ 暂不提供 | `start` 消息结构参考 **通信协议 §5** 与 `docs/protocol.md`；运行期以服务端实际下发为准 |
| `inquire_message.json` | ⛔ 暂不提供 | `inquire` 消息结构参考 **通信协议 §7 + 附录 B/C/D/F** 与 `docs/protocol.md`；运行期以每帧实际下发为准 |

## map_config.json 结构

顶层字段：

| 字段 | 说明 |
|---|---|
| `mapName` | 地图名称（当前："中等难度竞技地图"） |
| `map.maxX` / `map.maxY` | 网格尺寸 80 × 60 |
| `map.data` | 逗号分隔的扁平网格串（4800 个整数）：`0` 空白、`1` 官道、`2` 水路、`3` 山路、`4` 支路；`101-115` 为站点 S01-S15 的网格编码（协议附录 A）。仅用于展示/天气区域，寻路以 `edges[]` 为准 |
| `nodes[]` | `{nodeId, name, type, x, y}` —— S01-S15 |
| `edges[]` | `{fromNodeId, toNodeId, routeType, distance}` —— 21 条路线边（无 `edgeId`/`bidirectional`，方向以运行期合法相邻节点为准） |
| `safeZones[]` | 安全区（S15 兴庆宫） |
| `reverifyNode` | 重新验核节点（S14 朱雀门） |
| `processNodes[]` | `{nodeId, nodeName, processName, processRound}` —— 处理站点与读条帧数（中文 `processName`，非协议英文 `processType`） |
| `visibleResources[]` | `{nodeId, nodeName, resourceType, resourceName, visible}` —— 资源投放点（**无** `count`/`claimRound`） |

## ⚠️ map_config.json 与协议 `start` 的字段差异（M2 解析须注意）

`map_config.json` 是地图**原始配置**，是 `start.msg_data` 的**子集**。协议 `start`（§5）在此基础上额外携带运行期字段，M2 解析以 **`start` 实际下发**为准，不足处再回退到 map_config：

| 维度 | map_config.json | 协议 start / inquire |
|---|---|---|
| 路线边 | `fromNodeId/toNodeId/routeType/distance` | 另有 `edgeId`、`bidirectional`、`fromNode/toNode` 别名 |
| 处理点 | `processName`(中文)、`processRound` | `processType`(英文枚举)、`processRound`、`canWindow` |
| 资源 | `resourceType`、`visible` | 另有 `count`、`claimRound` |
| 任务 | 无 | `taskTemplates[]`（候选点/处理帧/分值）、`inquire.tasks[]` |
| 玩法语义 | `safeZones`/`reverifyNode` | `map.gameplay.roles`（起点/终点/宫门/安全区）、`taskCandidates`、`routeTaskBuckets`、`obstacleCandidateNodeIds` |

## 使用约定

- 只读参考；更新样例时在上表登记来源与抓取帧号。
- M2 起：`scripts/mock_server.py` 与 `client/tests/` 可加载 `map_config.json` 构造开局；`start`/`inquire` 的字段以协议文档为唯一结构依据。
