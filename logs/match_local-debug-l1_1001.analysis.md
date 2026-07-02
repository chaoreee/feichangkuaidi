# 对局分析报告：local-debug-l1

> 由 `analysis/` 自动生成。日志：`match_local-debug-l1_1001.jsonl`

## 1. 概览

| 指标 | 值 |
|---|---|
| 对局编号 | local-debug-l1 |
| 本方 playerId / 阵营 | 1001 / RED |
| 最大回合 | 600 |
| 结果类型 | NORMAL |
| 胜方 playerId | 2002 |
| 本方是否获胜 | False |
| 是否交付 | False |
| 交付回合 | 0 |
| 最终总分 | 80 |
| 交付/末帧好果 | 97 |
| 交付/末帧鲜度 | 72.53 |
| 皇榜任务分 | 180 |
| 末位置 / 状态 | S14 / WAITING |

## 2. 通信与决策

| 指标 | 值 |
|---|---|
| 总帧数(frame) | 600 |
| 决策次数 | 600 |
| 空动作心跳帧 | 577 |
| 平均决策耗时(ms) | 0.01 |
| 最大决策耗时(ms) | 1.1 |
| 决策超时帧(>400ms) | 0 |
| 错误记录数 | 0 |
| 异常次数 | 0 |

## 3. 动作与事件分布

提交动作统计：

- `CLAIM_TASK` × 8
- `MOVE` × 7
- `SQUAD_CLEAR` × 3
- `CLAIM_RESOURCE` × 2
- `PROCESS` × 2
- `USE_RESOURCE` × 2
- `CLEAR` × 1
- `RUSH_PROTECT` × 1
- `SQUAD_SCOUT` × 1

公开事件统计：

- `FRESHNESS_DROP` × 1035
- `MOVE_PROGRESS` × 772
- `WAIT` × 159
- `PROCESS_PROGRESS` × 99
- `TASK_REFRESH` × 22
- `NODE_ENTER` × 17
- `TASK_EXPIRE` × 11
- `GUARD_WEATHERING` × 8
- `TASK_COMPLETE` × 8
- `PROCESS_COMPLETE` × 7
- `GOOD_TO_BAD` × 4
- `RESOURCE_CLAIM` × 4
- `RESOURCE_USE` × 4
- `SQUAD_DISPATCH` × 4
- `SQUAD_CLEAR` × 3
- `BOUNTY_CREATE` × 2
- `BOUNTY_EXPIRE` × 2
- `GUARD_SET` × 2
- `ACTION_REJECTED` × 1
- `DELIVER_SUCCESS` × 1
- `OBSTACLE_CLEAR` × 1
- `RUSH_START` × 1
- `RUSH_TACTIC_USE` × 1
- `SCOUT_MARKER_ADD` × 1
- `SCOUT_MARKER_EXPIRE` × 1
- `SQUAD_SCOUT` × 1
- `VERIFY_GATE_COMPLETE` × 1

## 4. 效果评估

### 优点
- 皇榜任务基础分累计 180 ≥90（送达/用时满额并触发里程碑）

### 问题
- 未完成交付：送达/好果/鲜度/用时分归零（末位置=S14，状态=WAITING）

### 风险
- （无）

## 5. 改进建议

| 方向 | 问题 | 建议 |
|---|---|---|
| 交付 | 未完成交付 | 检查末帧状态(WAITING@S14)与时间预算：确认宫门验核后进入 S15，且交付时好果>0、鲜度>0；若因遇阻卡住，检查突破/绕行逻辑 |

## 6. 沉淀（回写基线）

- 将上述结论同步至 `AGENTS.md`（能力矩阵/迭代日志）与 `CHANGELOG.md`。
- 需要改代码的建议转为下一轮迭代任务。
