# samples/ — 协议与地图参考样例（reference fixtures）

本目录存放比赛的 **参考样例**，用作：规格核对、M2 `core.WorldState` 解析与寻路的开发依据、以及离线测试夹具。

> 这些是 **只读参考快照**，不是运行时权威。正式对战一切以服务端本局 `start` / 每帧 `inquire` 实际下发为准；
> 策略**禁止**硬编码这里的节点/路线/资源/任务位置（协议附录 A 明确要求）。样例文件不被 `client/` import，保证提交包纯净。
>
> ⚠️ **决赛/淘汰赛地图还会变**：本目录已含两张不同地图（见下表），且后续赛段可能再换新图。
> 一切节点/边/资源/处理点/任务候选点必须从运行期 `start` 动态读取，**禁止**按某张样例图适配。

## 文件清单

| 文件 | 状态 | 用途 / 内容 |
|---|---|---|
| `map_config.json` | ✅ 已更新（V4.2-MEDIUM） | **当前对战平台 + 36 强小组赛**所用地图的原始配置（`mapId=litchi_map_unity_full_coverage_v2`） |
| `map_config_variant_a.json` | ✅ 新增（V4.2-MEDIUM） | **36 进 8 淘汰赛** variant 地图（同 `mapId`/`designVersion` 外壳，边权/资源/处理点分布不同） |
| `start_message.json` | ⛔ 暂不提供 | `start` 消息结构参考 **通信协议 §5** 与 `docs/protocol.md`；运行期以服务端实际下发为准 |
| `inquire_message.json` | ⛔ 暂不提供 | `inquire` 消息结构参考 **通信协议 §7 + 附录 B/C/D/F** 与 `docs/protocol.md`；运行期以每帧实际下发为准 |

> 两张地图的 `mapId` / `mapName` / `designVersion` 完全相同——variant 是同一外壳下的内容变体（边权、处理点、资源投放、障碍候选点均不同）。不能据 `mapId` 判断"是哪张图"，必须以运行期 `start` 实际拓扑为准。

## map_config 结构（V4.2-MEDIUM，2026-07-05 起更新）

> **schema 已重构**：旧版顶层 `safeZones` / `reverifyNode` / `processNodes` / `visibleResources` 字段**已全部移除**，统一折叠进 `gameplay.*`；`edges[]` 增加 `edgeId` / `bidirectional` / `pathId`；新增 Unity 渲染相关字段（`grid` / `layers` / `legend` / `routePaths` / `assetMapping` / `dynamicRenderContract`）。M2 解析以 **`start` 实际下发**为准，不足处再回退到 map_config。

顶层字段：

| 字段 | 说明 |
|---|---|
| `schemaVersion` | `1.0` |
| `mapId` / `mapName` / `designVersion` | 地图标识 / 名称（"中等难度竞技地图"）/ 设计版本（`V4.2-MEDIUM`）。两图相同 |
| `grid` | `{width, height, tileSize, origin, xAxis, yAxis, unity2DMapping, unity3DMapping}`——Unity 渲染用网格规格（80×60，tileSize 1.0，origin TOP_LEFT，xAxis RIGHT，yAxis DOWN）。**无** 旧版 `map.maxX/maxY` |
| `map` | `{encoding:"csv", data:"..."}`——扁平 CSV 网格串（4800 个整数）。tile 编码见 `legend` |
| `legend` | tile 编码表：`0`EMPTY / `1`ROAD / `2`WATER / `3`MOUNTAIN / `4`BRANCH / `101-115`=S01-S15（站点编码 + 中文名，如 `103:S03_MEIGUAN_STATION`）。仅用于展示/天气区域，寻路以 `edges[]` 为准 |
| `layers` | Unity 图层组织（渲染用） |
| `nodes[]` | `{nodeId, code, name, type, x, y, icon}`——S01-S15，`code`=101-115 与 legend 对应，`type` 如 START/PROCESS/TERMINAL |
| `edges[]` | `{edgeId, fromNodeId, toNodeId, routeType, distance, bidirectional, pathId}`——23 条路线边。**新增** `edgeId` / `bidirectional`(均 True) / `pathId`(指向 `routePaths`) |
| `routePaths[]` | `{pathId, edgeId, points:[{x,y}...]}`——每条边的渲染折线点，与 `edges[].pathId` 对应 |
| `gameplay` | **玩法核心**，见下表（取代旧版散落的 `safeZones`/`reverifyNode`/`processNodes`/`visibleResources`） |
| `weatherRegionRule` | 天气区域渲染规则（HOT/HEAVY_RAIN/MOUNTAIN_FOG → weatherRegionCode + renderMode） |
| `assetMapping` / `dynamicRenderContract` | Unity 资源映射 / 动态渲染契约（渲染用，与策略无关） |

`gameplay` 子字段：

| 子字段 | 说明 |
|---|---|
| `roles` | `{startNodeId:"S01", terminalNodeIds:["S15"], gateNodeId:"S14", safeZoneNodeIds:["S15"], reverifyNodeId:"S14", rushExcludedNodeIds:["S11","S12","S13"]}`——起点/终点/宫门/安全区/重验核/RUSH 排除节点 |
| `processNodes[]` | `{nodeId, processType, processRound, canWindow}`——处理站点。`processType` 为**英文枚举**（TRANSFER/BOARD/WATER_TRANSFER/PASS_TRANSFER/PALACE_TRANSFER/VERIFY），**非**旧版中文 `processName`；`canWindow` 指示能否窗口出牌 |
| `resources[]` | `{nodeId, resourceType, count, claimRound}`——资源投放点。**含** `count`/`claimRound`（旧版 `visibleResources` 无），**无** `resourceName`/`visible` |
| `taskCandidates[]` | 皇榜任务候选点 id 列表（如 T01/T02/T04/T06/T08/T11/T12/T13/T14） |
| `routeTaskBuckets` | `{ROAD:[...], WATER:[...], MOUNTAIN:[...]}`——按路线类型分桶的任务候选节点 |
| `obstacleCandidateNodeIds` | 障碍候选节点 id 列表（运行期实际是否生成障碍以服务端为准） |

## ⚠️ map_config 与协议 `start` 的字段差异（M2 解析须注意）

`map_config.json` 是地图**原始配置**，是 `start.msg_data` 的**子集**。协议 `start`（§5）在此基础上额外携带运行期字段，M2 解析以 **`start` 实际下发**为准：

| 维度 | map_config（V4.2-MEDIUM） | 协议 start / inquire |
|---|---|---|
| 处理点 | `gameplay.processNodes[].processType`(英文枚举) + `processRound` + `canWindow` | 同名结构，运行期以服务端为准 |
| 资源 | `gameplay.resources[]`（`resourceType`/`count`/`claimRound`） | `inquire.nodes[].resourceStock` 等运行期实时库存 |
| 任务 | `gameplay.taskCandidates[]` + `routeTaskBuckets` | `taskTemplates[]`（候选点/处理帧/分值）、`inquire.tasks[]` |
| 玩法语义 | `gameplay.roles`（起点/终点/宫门/安全区/重验核/RUSH 排除） | `map.gameplay.roles`（同结构） |
| 渲染 | `grid`/`layers`/`legend`/`routePaths`/`assetMapping`/`dynamicRenderContract` | 不在 `start` 中（纯渲染，与策略无关） |

## 两张地图的关键差异（仅作参考，不驱动策略）

两图均为 15 节点 S01-S15、23 条边、6 个处理点、9 个任务候选点，但内容不同：

- **边权**：variant_a 多数边距离略增（±1 ~ +12），且 E18 边由 main 的 `S03→S06`（BRANCH, 38）改为 variant_a 的 `S02→S06`（BRANCH, 80）——拓扑发生一处结构性变化。
- **处理点**：main 为 `S04=BOARD(7)` / `S05=WATER_TRANSFER(6)`；variant_a 互换为 `S04=WATER_TRANSFER(6)` / `S05=BOARD(7)`。
- **障碍候选**：main `[S06,S08,S10,S11]`；variant_a `[S06,S07,S10,S11]`（S08→S07）。
- **资源投放**：main 20 项、variant_a 22 项，分布重排（如 variant_a 在 S06 增加 FAST_HORSE+OFFICIAL_PERMIT、S08 增加 ICE_BOX、S05 增加 SHORT_HORSE，PASS_TOKEN 从 S03 移到 S07，S06 不再有 ICE_BOX）。
- **routeTaskBuckets**：variant_a 的 ROAD 桶为 `[S03,S09,S10,S11,S13]`（main 含 S07 不含 S09 的位置互换）。
- **taskCandidates**：两图相同。

> 以上差异**仅供理解赛段地图多样性**。策略一律读 `start` 动态决策，不得据任何一张样例图硬编码路线/资源选择。

## 使用约定

- 只读参考；更新样例时在上表登记来源与赛段。
- `scripts/mock_server.py` / `scripts/sim_server.py` 已切到 V4.2-MEDIUM schema：从 `mc["gameplay"]["roles"|"processNodes"|"resources"]` + `mc["grid"]` 读取合成 `start`（运行期 client 读服务端 `start`，不读 map_config，本身不受影响）。`client/core/game_map.py` 本就 schema 无关（优先 `map.gameplay.*`，旧顶层字段作 fallback），无需改动。
- M2 起：`scripts/mock_server.py` 与 `client/tests/` 可加载 `map_config.json` 构造开局；`start`/`inquire` 的字段以协议文档为唯一结构依据。
