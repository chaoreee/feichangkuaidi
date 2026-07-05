# logs/ — 对局日志采集与分析目录（client 之外）

这里存放**从赛题平台/mock 取回的对局 trace 日志**，由仓库侧 `analysis/` 模块解析归因，驱动迭代。
本目录不属于交付件（`client/`），只用于本地/仓库侧的分析闭环。

## 日志从哪来

运行期 `client/` 把 trace 日志写在**包内** `client/logs/match_<matchId>_<playerId>.log`：

- 本地对 `scripts/mock_server.py` 跑：日志直接生成在 `client/logs/`（已 gitignore，不入库）。
- 提交到平台：交付件在平台运行时同样写 `client/logs/`；对战结束后连同交付件一起**下载回本地**。

## 采集与分析流程

1. 拿到一场对局的 `client/logs/match_*.log`，复制到本目录 `logs/`（按需归档，如 `logs/2026-07-04_<matchId>/`）。
2. 跑分析：`py -m analysis logs/match_xxx.log`（多场加 `--corpus`）→ 生成 `reports/<日期>_<matchId>.md`。
3. Claude Code 读 `reports/*.md`（结构化指标 + 归因结论）驱动 `client/` 迭代；必要时再回到原始 `.log` 取证。
4. 同步更新 `CLAUDE.md`（能力矩阵 + 迭代日志）与 `CHANGELOG.md`。

> **⚠️ 原始 trace 必须保留**：`reports/*.md` 只是蒸馏结论，逐帧取证（卡死段、鲜度跨阈值时点、设卡 ROI、预算漂移）必须回到原始 `.log`。
> 取回日志后**切勿删除原件**——本目录的 `.log` 入库长期保留（已确认 gitignore 不影响）。Iteration 12 的真机归因即因原件被清理、只剩 reports，导致无法逐帧深挖，仅能从聚合结论迭代。后续每场对局的 `.log` 都要原样留存。

## trace 行格式

每行一个事件，人类可读、可 grep：`<HH:MM:SS.mmm> <Event> matchId=..., round=N, k=v, k=v`。
事件类型（Iter 12 增厚后）：

| 事件 | 字段 | 说明 |
|---|---|---|
| `Startup` | playerId, host, port, version | 连接 |
| `Start` | teamId, camp, durationRound, nodes, edges, gate, terminals, processNodes | 开局地图角色 |
| `Ready` | round | 就绪 |
| `Frame` | round, phase, node, state, fresh, goodFruit, taskScore, verified, delivered, weather?, opp?, events | 每帧本方+天气+对手镜像+事件 |
| `Action` | round, action, target/task/.../extraGood, ms? | 每个动作 |
| `Block` | round, node, obstacle?, guardOwner?, guardDef?, cleared? | 阻塞快照（变化触发） |
| `Contest` | round, contestId, type, ri, myPt, oppPt, myCard, oppCard | 窗口每拍 |
| `Reject` | round, action, target, code | 被拒动作 |
| `Budget` | round, est, left | 交付估值 |
| `Over / Score` | 结算（逐队 Score 一行） |  |
| `Recv / Error / Shutdown` |  | 通信/异常/关闭 |

`opp=` 打包格式：`node|state|fresh|goodFruit|taskScore|verified|delivered`，缺段写 `-`（mock 蓝方 dummy 缺字段；真实平台下发实际值）。

示例：
```
11:26:29.711 Start matchId=mock_match_001, teamId=RED, camp=0, durationRound=600, nodes=15, edges=21, gate=S14, terminals=[S15], processNodes=[S02|S04|S05|S11|S13|S14]
11:26:29.712 Frame matchId=mock_match_001, round=5, phase=NORMAL, node=S07, state=IDLE, fresh=99.75, goodFruit=100, taskScore=0, verified=False, delivered=False, opp=S01|IDLE|0|0|0|F|F, events=[OBSTACLE_CLEAR]
11:26:29.712 Block matchId=mock_match_001, round=1, node=S13, obstacle=ROCKFALL, guardDef=0
11:26:29.727 Block matchId=mock_match_001, round=47, node=S10, guardOwner=RED, guardDef=6
11:26:29.712 Budget matchId=mock_match_001, round=72, est=310, left=528
```

本目录的 `.log` 文件会入库（供分析追溯）；`client/logs/` 下的运行期日志已 gitignore。
注：本地 mock 以追加模式累积多次对局到同一文件，`analysis/` 按 `Startup` 行切分会话，每会话一场。
