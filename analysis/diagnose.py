"""模式检测：MatchMetrics → Finding 列表（归因结论 + 改动建议）。

每个检测器对应一种真实败局模式。Finding.code 映射到报告章节与建议改动点。
检测器对缺失数据降级（mock 无对手/窗口时相应检测跳过）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analysis.metrics import MatchMetrics

# 阈值（与 config 对齐但硬编码，保持 analysis 独立）
STALL_FLAG_LEN = 5          # 卡死段 ≥5 帧即告警
FRESH_DELIVER_LOW = 70      # 交付鲜度低于此告警
CONVERSION_SERIOUS = 2      # 好果转坏 ≥2 篒告警
DRIFT_SERIOUS = 30          # 最终预算漂移 >30 帧告警
REJECT_LOOP = 3             # 同码拒绝 ≥3 次告警
RUSH_LATE_ROUND = 450       # RUSH 触发晚于此告警


@dataclass
class Finding:
    code: str            # NO_DELIVER / STALL / FRESHNESS_CRASH / BUDGET_DRIFT / EST_OVER_BUDGET / OFFENSIVE_BACKFIRE / RUSH_LATE / REJECT_LOOP / WINDOW_LOSS / SPOILAGE
    severity: str        # HIGH / MED / LOW
    title: str
    evidence: str
    suggestion: str


def diagnose(m: MatchMetrics) -> list:
    fs = []
    _no_deliver(m, fs)
    _stall(m, fs)
    _freshness(m, fs)
    _spoilage(m, fs)
    _budget(m, fs)
    _offensive(m, fs)
    _rush(m, fs)
    _reject(m, fs)
    _window(m, fs)
    return fs


def _no_deliver(m, fs):
    if not m.delivered and not m.retired:
        fs.append(Finding(
            code="NO_DELIVER", severity="HIGH",
            title="未交付",
            evidence="对局结束未交付（未退赛）。未交付则送达/好果/鲜度/用时四项归零，任务分封顶 80。",
            suggestion="查卡死段/阻塞 encounters/预算漂移定位阻断点；优先保交付。"))
    elif m.retired:
        fs.append(Finding(
            code="NO_DELIVER", severity="HIGH",
            title="退赛",
            evidence="本方退赛（连续 60 帧缺动作）。",
            suggestion="查决策异常/连接断开；main.py 已对单帧异常降级心跳，疑为连接层问题。"))


def _stall(m, fs):
    for s in m.stalls:
        sev = "HIGH" if s.length >= 10 else ("MED" if s.length >= STALL_FLAG_LEN else "LOW")
        if s.length < STALL_FLAG_LEN:
            continue
        fs.append(Finding(
            code="STALL", severity=sev,
            title="卡死段 @%s（r%d–r%d，%d帧）" % (s.node, s.start_round, s.end_round, s.length),
            evidence="state=%s 连续 %d 帧动作 NONE 且未前进（Iteration 8 复发模式）。" % (s.state, s.length),
            suggestion="查 _keep_moving 是否在该状态重发 MOVE；疑服务端 park 成 WAITING 未续行。"))


def _freshness(m, fs):
    if m.good_fruit_loss_conversion >= CONVERSION_SERIOUS:
        sev = "HIGH" if m.good_fruit_loss_conversion >= 4 else "MED"
        crosses = ", ".join("r%d×%d" % (c.round, c.threshold) for c in m.threshold_crosses[:5])
        fs.append(Finding(
            code="FRESHNESS_CRASH", severity=sev,
            title="鲜度崩盘：好果转坏 %d 篒" % m.good_fruit_loss_conversion,
            evidence="鲜度跨越阈值 %d 次（%s），每次触发 1 篒好果转坏，损失好果分 ~%.1f/果。" % (
                m.good_fruit_loss_conversion, crosses or "—",
                m.good_fruit_loss_conversion * 1.8),
            suggestion="查冰鉴是否在阈值上方提前使用挡阈值（_freshness_rescue）；查绕路/卡死导致鲜度损耗累积。"))
    if m.fresh_at_deliver is not None and m.fresh_at_deliver < FRESH_DELIVER_LOW:
        fs.append(Finding(
            code="FRESHNESS_CRASH", severity="MED",
            title="交付鲜度偏低：%.1f" % m.fresh_at_deliver,
            evidence="交付鲜度 %.1f < %d，鲜度分 = floor(鲜度/100×180) 损失显著。" % (
                m.fresh_at_deliver, FRESH_DELIVER_LOW),
            suggestion="查护果令是否在 RUSH 阶段低鲜度时使用；查鲜度路由（freshness_weight）是否偏好水路。"))


def _spoilage(m, fs):
    if m.good_fruit_loss_unattributed > 0:
        fs.append(Finding(
            code="SPOILAGE", severity="MED",
            title="好果未归因损失 %d 篒" % m.good_fruit_loss_unattributed,
            evidence="好果总损失 %d = 转坏 %d + 动作消耗 %d + 未归因 %d。未归因多为鲜度归零报废。" % (
                m.good_fruit_loss_total, m.good_fruit_loss_conversion,
                m.good_fruit_loss_spend, m.good_fruit_loss_unattributed),
            suggestion="查鲜度是否曾归零触发全量报废（§3.2.1 顺序 4）。"))


def _budget(m, fs):
    if m.est_over_left_max > 0:
        fs.append(Finding(
            code="EST_OVER_BUDGET", severity="HIGH",
            title="预算曾预测超时：est 超出剩余 %d 帧" % m.est_over_left_max,
            evidence="某帧 _deliver_estimate 估值 > 剩余帧，曾面临无法按时交付风险。",
            suggestion="查 _can_afford 是否过乐观（未计设卡/障碍税）；降低 DELIVER_TIME_SAFETY_MARGIN 风险。"))
    if m.final_drift is not None and m.final_drift > DRIFT_SERIOUS:
        fs.append(Finding(
            code="BUDGET_DRIFT", severity="MED",
            title="预算系统性低估：%d 帧" % m.final_drift,
            evidence="实际交付比末帧估值晚 %d 帧（> %d）。" % (m.final_drift, DRIFT_SERIOUS),
            suggestion="查 _deliver_estimate 未计入的成本（处理耗时/天气/绕行）；据此调高安全余量。"))


def _offensive(m, fs):
    wasted = [g for g in m.guards if not g.opp_passed]
    if wasted:
        sev = "MED" if len(wasted) >= 2 else "LOW"
        nodes = ", ".join(g.node for g in wasted[:4])
        fs.append(Finding(
            code="OFFENSIVE_BACKFIRE", severity=sev,
            title="进攻设卡未拖延对手：%d 处" % len(wasted),
            evidence="设卡节点 %s 对手未经过（纯成本无收益）：每处耗 4 帧 + 好果。" % nodes,
            suggestion="查 _opp_will_pass 判断是否过乐观；领先时 OFFENSIVE_LEAD_SKIP 已回避悬赏？调 OFFENSIVE_MIN_OPP_DELAY。"))


def _rush(m, fs):
    if m.rush_start_round is not None and m.rush_start_round > RUSH_LATE_ROUND:
        fs.append(Finding(
            code="RUSH_LATE", severity="MED",
            title="RUSH 触发过晚：r%d" % m.rush_start_round,
            evidence="宫宴冲刺 r%d 才触发（> %d），验核+交付挤在末尾。" % (
                m.rush_start_round, RUSH_LATE_ROUND),
            suggestion="查是否因绕路/卡死导致到 S14 过晚；RUSH 后验核可绑 BREAK_ORDER 减 3 帧。"))
    if (m.verify_end_round is not None and m.deliver_round is not None
            and m.deliver_round - m.verify_end_round > 20):
        fs.append(Finding(
            code="RUSH_LATE", severity="LOW",
            title="验核后到交付耗时较长：%d 帧" % (m.deliver_round - m.verify_end_round),
            evidence="验核完成 r%d → 交付 r%d，间隔 %d 帧。" % (
                m.verify_end_round, m.deliver_round, m.deliver_round - m.verify_end_round),
            suggestion="查验核后路径是否遇阻；终局可用疾行令（RUSH_SPEED）冲刺。"))


def _reject(m, fs):
    for code, cnt in m.reject_hist.items():
        if cnt >= REJECT_LOOP:
            fs.append(Finding(
                code="REJECT_LOOP", severity="MED",
                title="重复拒绝：%s ×%d" % (code, cnt),
                evidence="拒绝码 %s 出现 %d 次（≥%d）。" % (code, cnt, REJECT_LOOP),
                suggestion="查 _apply_rejection_feedback 拉黑绕行是否生效；该码对应动作的目标是否反复撞同一阻塞。"))


def _window(m, fs):
    for w in m.windows:
        if w.my_win is False and (w.net_guard_cost > 0 or w.net_good_cost > 0):
            fs.append(Finding(
                code="WINDOW_LOSS", severity="LOW",
                title="窗口告负 %s（%s）净耗资源" % (w.contest_id, w.type or "?"),
                evidence="本方输窗：出牌 %s，耗护卫点 %d / 好果 %d。" % (
                    w.my_cards, w.net_guard_cost, w.net_good_cost),
                suggestion="查 _window_card 反应式出牌是否被针对；低筹码窗口考虑直接弃权省成本。"))
