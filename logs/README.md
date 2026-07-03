# logs/ — 对局日志采集与分析目录（client 之外）

这里存放**从赛题平台/mock 取回的对局 trace 日志**，供 Claude Code 直接阅读、分析、驱动迭代。
本目录不属于交付件（`client/`），只用于本地/仓库侧的分析闭环。

## 日志从哪来

运行期 `client/` 把 trace 日志写在**包内** `client/logs/match_<matchId>_<playerId>.log`：

- 本地对 `scripts/mock_server.py` 跑：日志直接生成在 `client/logs/`（已 gitignore，不入库）。
- 提交到平台：交付件在平台运行时同样写 `client/logs/`；对战结束后连同交付件一起**下载回本地**。

## 采集流程

1. 拿到一场对局的 `client/logs/match_*.log`。
2. 复制（或经 GitHub 上传）到本目录 `logs/`，按需重命名/归档，例如 `logs/2026-07-02_local-debug-l1/`。
3. 让 Claude Code 直接读这些 `.log`（trace 文本，无需 JSON 解析或 python 分析模块），产出分析结论并驱动 `client/` 迭代。
4. 同步更新 `CLAUDE.md`（能力矩阵 + 迭代日志）与 `CHANGELOG.md`。

## trace 行格式

每行一个事件，人类可读、可 grep：

```
12:03:41.271 Action matchId=local-debug-l1, round=96, action=MOVE, target=S05
12:03:41.272 Frame matchId=local-debug-l1, round=96, phase=NORMAL, node=S05, state=MOVING, fresh=97.25, goodFruit=100, verified=false, delivered=false
```

事件类型：`Startup / Register / Start / Ready / Frame / Action / Recv / Error / Over / Score / Shutdown`。
本目录的 `.log` 文件会入库（供分析追溯）；`client/logs/` 下的运行期日志已 gitignore。
