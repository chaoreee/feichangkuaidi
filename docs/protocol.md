# 通信协议要点摘要（protocol.md）

> 本文件是实现速查摘要，**权威原文**为仓库根 `一骑红尘：荔枝争运战 通信协议.md`。冲突以原文为准。

## 传输层（§1）
- TCP 字节流；帧 = **5 位十进制长度前缀（body 的 UTF-8 字节数，≤99999）+ UTF-8 JSON body**。
- 必须处理：半包（缓存到齐）、粘包（按前缀循环拆）、中文跨包（先字节后解码）。
- 消息边界只按长度前缀判断，禁止按换行/read 次数判断。

## 消息流程（§2）
`registration → start → ready(round=1) → loop{ inquire(N) → action(round=N) } → over`
- `action.round` 必须 == 当前 `inquire.round`；round N 结果在下一帧 inquire 的 `events[]`/`actionResults[]`。
- 无动作也必发 `actions: []`（有效心跳，不计缺失）；截止前未收到才算缺动作。

## 五类下发消息
| 消息 | 关键字段 | 客户端动作 |
|---|---|---|
| `start`（§5） | matchId, durationRound(600), players[](识别本方 playerId/teamId), nodes[], edges[](fromNodeId/toNodeId/routeType/distance/bidirectional), resources[], taskTemplates[], map.gameplay(roles/resources/processNodes/taskCandidates/routeTaskBuckets/obstacleCandidateNodeIds) | 缓存静态信息；优先读顶层 nodes/edges |
| `inquire`（§7） | round, phase(NORMAL/RUSH/ENDED), players[], nodes[], edges[], weather, tasks[], bounties[], contests[], events[], actionResults[], scorePreview | 每帧决策入口 |
| `over`（§9） | resultType(NORMAL/DRAW/FORFEIT/INVALID), winnerPlayerId, players[].totalScore/scoreDetail | 读最终胜负 |
| `error`（§11） | round, playerId, errorCode, message | 立即错误，修正发包 |
| `actionResults`（§10，内嵌于 inquire） | round, playerId, action, accepted, result, errorCode | 上一帧动作摘要 |

## 运行时状态对象（附录 B/C/D）
- `players[]`：state, currentNodeId, nextNodeId, routeEdgeId, moveProgress, edgeProgressMs/edgeTotalMs, freshness, goodFruit/frozenGoodFruit/badFruit, squadAvailable/InFlight, guardActionPoint, verified, delivered, retired, missingActionRounds, illegalActionCount, penaltyScore, rushTacticUsedCount, buffs[], currentProcess, resources{}, taskScore/bountyScore/totalScore/scoreDetail
- `nodes[]`：nodeType, processType/processRound, guard{ownerTeamId,defense,maxDefense,completeRound,active}, resourceStock{}, scouted[]{teamId,remainRound,processReduceRound,remainingTriggers}, hasObstacle/obstacleType, obstacleResidue{...,taxRound=6}, canWindow
- `weather`：active[]{type(HOT/HEAVY_RAIN/MOUNTAIN_FOG),region(ALL/WATER/MOUNTAIN),remainRound}, forecast[]{startRound,durationRound=60}
- `currentProcess.objectKey` 格式：`TASK:{id}` / `RESOURCE:{node}:{type}` / `GATE:{node}` / `OBSTACLE:{node}` / `PASS:{node}` / `GUARD:{node}` / `PROCESS:{node}:{type}`

## 动作字段矩阵（§8 / 附录 E）
见 `docs/delivery_spec.md` §1.2。要点：字段名大小写敏感；`BREAK_ORDER` 只作 `rushTactic` 绑定；`VERIFY_GATE` 仅 `phase=RUSH` 后可提交；`DOCK` 仅 `processType=BOARD`；`PROCESS` 目标须当前节点。

## 错误码（§11）
- 立即 error：INVALID_LENGTH_PREFIX / INVALID_JSON / INVALID_ACTION_TYPE / ACTION_REJECTED(未知 msg_name) / MATCH_ID_MISMATCH / ACTION_TOO_LATE / DUPLICATE_ACTION / PLAYER_ADDRESS_MISMATCH / PLAYER_NOT_ALLOWED / MATCH_ALREADY_STARTED / PLAYER_LIMIT_EXCEEDED
- 规则拒绝/非法（走 events[]+actionResults[]）：INVALID_ACTION_CONFLICT / PARAM_OUT_OF_RANGE / MOVING_ACTION_FORBIDDEN / RESTING_ACTION_FORBIDDEN / SAFE_ZONE_FORBIDDEN / PROCESS_REQUIRED / PROCESS_NOT_AVAILABLE / NOT_AT_TARGET_NODE / MOVE_* / TARGET_NOT_* / RESOURCE_NOT_* / TASK_* / OBJECT_BUSY / WINDOW_DRAW_RETRY_LIMIT / VERIFY_REQUIRED / ALREADY_VERIFIED / DELIVER_* / ALREADY_DELIVERED / RUSH_TACTIC_INVALID_BINDING / HORSE_BUFF_CONFLICT / FORCED_PASS_REPEAT / OBSTACLE_NOT_FOUND

## 事件类型（附录 F，判断动作是否真正生效）
关注：MOVE_PROGRESS/NODE_ENTER、PROCESS_COMPLETE、RESOURCE_CLAIM/USE、TASK_COMPLETE/EXPIRE/PROTECTION_START、WINDOW_CONTEST_START/END/DRAW/*_WIN、GUARD_SET/BREAK/WEATHERING、FORCED_PASS_*、BOUNTY_*、RUSH_START/TACTIC_USE、VERIFY_GATE_COMPLETE、DELIVER_SUCCESS、POST_DELIVER_PENALTY、FRESHNESS_DROP/GOOD_TO_BAD/GOOD_FRUIT_SCRAP、SCOUT_MARKER_*、SQUAD_*、PLAYER_RETIRED、ACTION_REJECTED/INVALID_ACTION。
