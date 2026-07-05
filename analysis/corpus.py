"""跨场聚合：多场 MatchMetrics → 复发模式统计 + 胜负分组对比。

输出 Markdown 汇总报告，识别跨场复发问题（如"X/Y 场卡死于同一节点"）。
"""

from __future__ import annotations

from collections import Counter

from analysis.metrics import MatchMetrics


def aggregate(items):
    """items: list of (match_id, MatchMetrics, findings)。返回 Markdown 字符串。"""
    lines = []
    h = lines.append
    h("# 跨场聚合报告")
    h("")
    n = len(items)
    h("共 %d 场对局。" % n)
    h("")

    # 胜负
    wins = sum(1 for _, m, _ in items if m.i_won)
    delivered = sum(1 for _, m, _ in items if m.delivered)
    h("- 胜：**%d/%d**" % (wins, n))
    h("- 交付：%d/%d" % (delivered, n))
    if delivered:
        avg_round = sum(m.deliver_round for _, m, _ in items if m.deliver_round) / delivered
        avg_fresh = sum(m.fresh_at_deliver for _, m, _ in items
                        if m.fresh_at_deliver is not None) / delivered
        h("- 平均交付帧：%.1f" % avg_round)
        h("- 平均交付鲜度：%.2f" % avg_fresh)
    h("")

    # 复发诊断
    h("## 复发诊断模式")
    h("")
    code_counts = Counter()
    code_examples = {}
    for _, _, fs in items:
        seen = set()
        for f in fs:
            if f.code in seen:
                continue
            seen.add(f.code)
            code_counts[f.code] += 1
            code_examples.setdefault(f.code, []).append(f.title)
    if not code_counts:
        h("_未检出异常模式。_")
        h("")
    else:
        h("| 模式 | 出现场次 | 示例 |")
        h("|---|---|---|")
        for code, cnt in code_counts.most_common():
            ex = code_examples[code][:3]
            h("| %s | %d/%d | %s |" % (code, cnt, n, "; ".join(ex)))
        h("")

    # 卡死节点复发
    stall_nodes = Counter()
    for _, m, _ in items:
        for s in m.stalls:
            stall_nodes[s.node] += 1
    if stall_nodes:
        h("## 卡死节点复发")
        h("")
        h("| 节点 | 卡死段次数 |")
        h("|---|---|")
        for node, cnt in stall_nodes.most_common():
            h("| %s | %d |" % (node, cnt))
        h("")

    # 每场速览
    h("## 每场速览")
    h("")
    h("| 对局 | 结果 | 交付帧 | 鲜度 | 好果 | 任务 | 总分 | 诊断数 |")
    h("|---|---|---|---|---|---|---|---|")
    for mid, m, fs in items:
        result = "胜" if m.i_won else ("负" if m.i_won is False else "—")
        h("| %s | %s | %s | %s | %s | %s | %s | %d |" % (
            mid, result,
            m.deliver_round or "—",
            _fmt(m.fresh_at_deliver), _fmt(m.good_fruit_at_deliver),
            _fmt(m.task_score), _fmt(m.total_score), len(fs)))
    h("")
    return "\n".join(lines) + "\n"


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)
