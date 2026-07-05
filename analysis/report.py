"""Markdown 报告渲染：MatchTrace + MatchMetrics + Findings → Markdown 字符串。"""

from __future__ import annotations

from analysis.metrics import MatchMetrics
from analysis.parser import MatchTrace


def render(trace: MatchTrace, m: MatchMetrics, findings) -> str:
    lines = []
    h = lines.append
    mid = m.match_id or "(unknown)"
    h("# 对局分析报告：%s" % mid)
    h("")
    _summary(h, m, findings)
    _scores(h, trace, m)
    _freshness(h, m)
    _stalls(h, m)
    _blocks(h, m)
    _budget(h, m)
    _windows(h, m)
    _guards(h, m)
    _rush(h, m)
    _histograms(h, m)
    _diagnose(h, findings)
    return "\n".join(lines) + "\n"


def _summary(h, m, findings):
    high = sum(1 for f in findings if f.severity == "HIGH")
    med = sum(1 for f in findings if f.severity == "MED")
    low = sum(1 for f in findings if f.severity == "LOW")
    result = "胜" if m.i_won else ("负" if m.i_won is False else "未知")
    delivered = "是" if m.delivered else "否"
    h("## 摘要")
    h("")
    h("| 项 | 值 |")
    h("|---|---|")
    h("| 结果 | %s |" % result)
    h("| 交付 | %s%s |" % (delivered, ("（r%d）" % m.deliver_round) if m.deliver_round else ""))
    h("| 交付鲜度 | %s |" % _fmt(m.fresh_at_deliver))
    h("| 交付好果 | %s |" % _fmt(m.good_fruit_at_deliver))
    h("| 任务分 | %s |" % _fmt(m.task_score))
    h("| 悬赏分 | %s |" % _fmt(m.bounty_score))
    h("| 总分 | %s |" % _fmt(m.total_score))
    h("| 总帧 | %d |" % m.duration)
    h("| 诊断 | HIGH×%d  MED×%d  LOW×%d |" % (high, med, low))
    h("")


def _scores(h, trace, m):
    if not trace.scores:
        return
    h("## 分项得分")
    h("")
    h("| 玩家 | 本方 | 交付 | 交付帧 | 鲜度 | 好果 | 任务分 | 悬赏分 | 总分 |")
    h("|---|---|---|---|---|---|---|---|---|")
    for s in trace.scores:
        h("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            s.player, "✔" if s.me else "",
            "是" if s.delivered else "否",
            s.deliver_round if s.deliver_round else "—",
            _fmt(s.fresh), _fmt(s.good_fruit), _fmt(s.task_score),
            _fmt(s.bounty_score), _fmt(s.total)))
    h("")


def _freshness(h, m):
    h("## 鲜度归因")
    h("")
    h("| 项 | 值 |")
    h("|---|---|")
    h("| 交付鲜度 | %s |" % _fmt(m.fresh_at_deliver))
    h("| 好果转坏（篓） | %d |" % m.good_fruit_loss_conversion)
    h("| 好果动作消耗（篓） | %d |" % m.good_fruit_loss_spend)
    h("| 好果未归因损失（篓） | %d |" % m.good_fruit_loss_unattributed)
    h("| 好果总损失（篓） | %d |" % m.good_fruit_loss_total)
    h("")
    if m.threshold_crosses:
        h("阈值跨越（每次触发 1 篒好果转坏）：")
        h("")
        h("| 帧 | 阈值 | 鲜度前 | 鲜度后 |")
        h("|---|---|---|---|")
        for c in m.threshold_crosses:
            h("| r%d | %d | %.2f | %.2f |" % (c.round, c.threshold, c.fresh_before, c.fresh_after))
        h("")
    else:
        h("_无好果转坏阈值跨越（鲜度未跌破 90）。_")
        h("")


def _stalls(h, m):
    h("## 卡死段")
    h("")
    if not m.stalls:
        h("_无卡死段（state∈{MOVING,WAITING} 且动作 NONE 且未前进的连续段）。_")
        h("")
        return
    h("| 起 | 止 | 节点 | 状态 | 帧数 |")
    h("|---|---|---|---|---|")
    for s in m.stalls:
        h("| r%d | r%d | %s | %s | %d |" % (s.start_round, s.end_round, s.node, s.state, s.length))
    h("")


def _blocks(h, m):
    h("## 阻塞 encounters")
    h("")
    if not m.encounters:
        h("_无阻塞记录。_")
        h("")
        return
    h("| 节点 | 类型 | 归属 | 起 | 止 | 解决 | 持续帧 |")
    h("|---|---|---|---|---|---|---|")
    for e in m.encounters:
        h("| %s | %s | %s | r%s | r%s | %s | %s |" % (
            e.node, e.kind, e.owner or "—", e.start_round,
            e.end_round or "—", e.resolution or "—", e.duration if e.duration is not None else "—"))
    h("")


def _budget(h, m):
    h("## 预算漂移")
    h("")
    h("| 项 | 值 |")
    h("|---|---|")
    h("| 预算轨迹点数 | %d |" % len(m.budget_traj))
    h("| est 超出剩余最大值 | %d 帧（正=曾预测超时） |" % m.est_over_left_max)
    h("| 最终漂移 | %s |" % (_fmt(m.final_drift) if m.final_drift is not None else "—"))
    if m.budget_traj:
        r0, e0, l0 = m.budget_traj[0]
        r1, e1, l1 = m.budget_traj[-1]
        h("| 首帧 | r%d est=%d left=%d |" % (r0, e0, l0))
        h("| 末帧 | r%d est=%d left=%d |" % (r1, e1, l1))
    h("")


def _windows(h, m):
    h("## 窗口争夺")
    h("")
    if not m.windows:
        h("_无窗口记录（mock 无窗口；真实对局此处列出每窗口胜负与净成本）。_")
        h("")
        return
    h("| 窗口 | 类型 | 胜负 | 本方牌 | 对手牌 | 护卫点 | 好果 |")
    h("|---|---|---|---|---|---|---|")
    for w in m.windows:
        win = "胜" if w.my_win else ("负" if w.my_win is False else "—")
        h("| %s | %s | %s | %s | %s | %d | %d |" % (
            w.contest_id, w.type or "—", win,
            "|".join(w.my_cards) or "—", "|".join(w.opp_cards) or "—",
            w.net_guard_cost, w.net_good_cost))
    h("")


def _guards(h, m):
    h("## 进攻设卡 ROI")
    h("")
    if not m.guards:
        h("_无进攻设卡记录。_")
        h("")
        return
    h("| 节点 | 种卡帧 | extra好果 | 增援 | 对手经过 | 成本帧 |")
    h("|---|---|---|---|---|---|")
    for g in m.guards:
        h("| %s | r%d | %d | %s | %s | %d |" % (
            g.node, g.set_round, g.extra_good,
            "r%d" % g.reinforce_round if g.reinforced else "否",
            "r%d" % g.opp_pass_round if g.opp_passed else "否",
            g.cost_frames))
    h("")


def _rush(h, m):
    h("## RUSH 时点")
    h("")
    h("| 项 | 值 |")
    h("|---|---|")
    h("| RUSH 触发 | %s |" % ("r%d" % m.rush_start_round if m.rush_start_round else "—"))
    h("| 验核开始 | %s |" % ("r%d" % m.verify_start_round if m.verify_start_round else "—"))
    h("| 验核完成 | %s |" % ("r%d" % m.verify_end_round if m.verify_end_round else "—"))
    h("| 交付 | %s |" % ("r%d" % m.deliver_round if m.deliver_round else "—"))
    h("")


def _histograms(h, m):
    h("## 动作直方图")
    h("")
    if m.action_hist:
        items = sorted(m.action_hist.items(), key=lambda kv: -kv[1])
        h("| 动作 | 次数 |")
        h("|---|---|")
        for a, c in items:
            h("| %s | %d |" % (a, c))
        h("")
    h("- NONE 心跳占比：%.1f%%" % (m.none_heartbeat_ratio * 100 if m.none_heartbeat_ratio else 0))
    if m.reject_hist:
        h("- 拒绝码直方图：%s" % ", ".join("%s×%d" % kv for kv in m.reject_hist.items()))
    h("")


def _diagnose(h, findings):
    h("## 诊断结论")
    h("")
    if not findings:
        h("_未检出异常模式。_")
        h("")
        return
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    for f in sorted(findings, key=lambda f: order.get(f.severity, 9)):
        h("### [%s] %s — %s" % (f.severity, f.code, f.title))
        h("")
        h("- **证据**：%s" % f.evidence)
        h("- **建议**：%s" % f.suggestion)
        h("")


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)
