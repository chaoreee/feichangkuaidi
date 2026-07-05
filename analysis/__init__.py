"""分析模块（非交付件，纯 stdlib）。

把 client/ 取回的 trace 日志解析成结构化指标 + 归因结论 + Markdown 报告。

数据流：trace .log → parser.MatchTrace → metrics.MatchMetrics → diagnose.Finding → report.Markdown
入口：`python -m analysis <log...> [--corpus]`
"""
