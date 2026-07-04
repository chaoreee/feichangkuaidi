"""仓库侧分析模块（**位于 client 之外**，非交付件）。

职责：把对局结束后取回的运行期 trace 日志（`match_*.log`）解析为结构化单局报告，
再跨局聚合为 `analysis_report.md` / `ab_report.md`。**只抽取事实、不做优化、不出建议**——
建议留给 AI 与人（见 `docs/iteration_plan_v2.md` §2）。

分工边界：
- `client/`（交付件）只记录人类可读 trace 日志，不做任何分析、不写结构化报告。
- `analysis/`（本包，仓库侧）事后解析多份 trace → 单局 Report → 跨局聚合报告。
- AI 只读聚合报告做归因，不直读 10w 字原始 trace。

模块：
- `parser.parse_log(path) -> Report`：单局 trace → 结构化 Report（schemaVersion=1）。
- `aggregator`：跨局统计 / 场景分段 / 运气分类 / 异常局标记 / seed 配对 A/B / `rules.py` 对账自检。
- `__main__`：CLI——扫描目录下的 `*.log`，解析+聚合，写出 `docs/analysis_report.md`(+`ab_report.md`)。
"""
