"""报告生成：渲染 analysis.md 并落盘。CLI：python -m analysis <logfile|dir>。"""

import os

from analysis.evaluator import evaluate
from analysis.optimizer import suggest
from analysis.parser import parse_log


def _kv_table(pairs):
    lines = ["| 指标 | 值 |", "|---|---|"]
    lines += ["| %s | %s |" % (k, v) for k, v in pairs]
    return "\n".join(lines)


def _hist_block(title, hist):
    if not hist:
        return "%s：无\n" % title
    items = sorted(hist.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return "%s：\n\n" % title + "\n".join("- `%s` × %d" % (k, v) for k, v in items) + "\n"


def _bullets(items):
    return "\n".join("- %s" % s for s in items) + "\n" if items else "- （无）\n"


def render(parsed, ev, suggestions):
    d = ev["decision"]
    md = []
    md.append("# 对局分析报告：%s" % (parsed.get("match_id") or "unknown"))
    md.append("")
    md.append("> 由 `analysis/` 自动生成。日志：`%s`" % os.path.basename(parsed.get("log_file") or ""))
    md.append("")
    md.append("## 1. 概览")
    md.append("")
    md.append(_kv_table([
        ("对局编号", parsed.get("match_id")),
        ("本方 playerId / 阵营", "%s / %s" % (parsed.get("player_id"), parsed.get("team_id"))),
        ("最大回合", parsed.get("duration_round")),
        ("结果类型", ev["result_type"]),
        ("胜方 playerId", ev["winner_player_id"]),
        ("本方是否获胜", ev["won"]),
        ("是否交付", ev["delivered"]),
        ("交付回合", ev["deliver_round"]),
        ("最终总分", ev["final_score"]),
        ("交付/末帧好果", ev["final_good"]),
        ("交付/末帧鲜度", ev["final_freshness"]),
        ("皇榜任务分", ev["task_score"]),
        ("末位置 / 状态", "%s / %s" % (ev["last_node"], ev["last_state"])),
    ]))
    md.append("")
    md.append("## 2. 通信与决策")
    md.append("")
    md.append(_kv_table([
        ("总帧数(frame)", ev["frames_total"]),
        ("决策次数", d["count"]),
        ("空动作心跳帧", ev["heartbeat_frames"]),
        ("平均决策耗时(ms)", d["avg_ms"]),
        ("最大决策耗时(ms)", d["max_ms"]),
        ("决策超时帧(>400ms)", d["over_budget"]),
        ("错误记录数", ev["error_count"]),
        ("异常次数", ev["exception_count"]),
    ]))
    md.append("")
    md.append("## 3. 动作与事件分布")
    md.append("")
    md.append(_hist_block("提交动作统计", ev["action_histogram"]))
    md.append(_hist_block("公开事件统计", ev["event_histogram"]))
    md.append("## 4. 效果评估")
    md.append("")
    md.append("### 优点")
    md.append(_bullets(ev["strengths"]))
    md.append("### 问题")
    md.append(_bullets(ev["problems"]))
    md.append("### 风险")
    md.append(_bullets(ev["risks"]))
    md.append("## 5. 改进建议")
    md.append("")
    md.append("| 方向 | 问题 | 建议 |")
    md.append("|---|---|---|")
    for area, issue, sug in suggestions:
        md.append("| %s | %s | %s |" % (area, issue, sug))
    md.append("")
    md.append("## 6. 沉淀（回写基线）")
    md.append("")
    md.append("- 将上述结论同步至 `AGENTS.md`（能力矩阵/迭代日志）与 `CHANGELOG.md`。")
    md.append("- 需要改代码的建议转为下一轮迭代任务。")
    md.append("")
    return "\n".join(md)


def analyze(path, out_path=None):
    parsed = parse_log(path)
    ev = evaluate(parsed)
    suggestions = suggest(parsed, ev)
    md = render(parsed, ev, suggestions)
    if out_path is None:
        log_fp = parsed["log_file"]
        stem = os.path.splitext(os.path.basename(log_fp))[0]
        out_path = os.path.join(os.path.dirname(log_fp), stem + ".analysis.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    return out_path
