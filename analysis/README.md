# analysis/ — 赛后日志分析框架

开发期离线工具（不参与提交物）。解析 client 运行期写出的 JSONL 日志，评估表现、给出改进建议、产出 `analysis.md`，形成"日志→分析→优化→回写基线"闭环。

## 管线

```
parser.py    JSONL → 结构化对局数据（只取最近一次会话）
evaluator.py 结构化数据 → 指标 + 优点/问题/风险
optimizer.py 评估 → (方向, 问题, 建议) 列表
report.py    渲染 analysis.md 并落盘
```

## 用法

```bash
# 分析单个日志文件或目录（目录取最近修改的 .jsonl）
python -m analysis logs/match_xxx.jsonl
python -m analysis logs/            # 目录

# 输出：与日志同目录下 <日志名>.analysis.md
```

日志格式见 `client/logger/match_logger.py`：每行 `{ts, round, kind, matchId, payload}`，
`kind ∈ recv / send / decide / state / error / frame`。其中 `frame` 记录每帧本方状态与事件类型，
`decide` 记录提交动作与决策耗时，`recv msg=over` 记录最终结算。

## 沉淀

每轮分析后，把结论回写 `AGENTS.md`（能力矩阵/迭代日志）与 `CHANGELOG.md`，
需要改代码的建议转为下一轮迭代任务；真实对局的 `analysis.md` 建议随对局日志一并归档到 `logs/match_xxx/`。

## 报告结构

概览（交付/得分/鲜度/任务分）→ 通信与决策（帧数/耗时/错误）→ 动作与事件分布 →
效果评估（优点/问题/风险）→ 改进建议（表格）→ 沉淀清单。
