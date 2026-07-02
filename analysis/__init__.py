"""analysis：赛后离线日志分析框架（parser → evaluator → optimizer → report）。

解析 client 运行期写出的 JSONL 日志（logger/match_logger.py 格式：每行 {ts,round,kind,matchId,payload}），
评估表现、给出改进建议、产出 analysis.md。开发期离线运行，不参与提交物。
"""
