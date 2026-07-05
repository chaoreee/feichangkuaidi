"""单场指标计算：MatchTrace → MatchMetrics。

指标对齐真实败局模式：交付/鲜度归因/卡死段/阻塞 encounters/预算漂移/窗口/进攻设卡ROI/RUSH时点/直方图。
所有指标对缺失数据降级（mock 无对手/窗口/天气时相应指标为 None/空，不报错）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from analysis.parser import MatchTrace

# 鲜度首次低于这些阈值各触发 1 篒好果转坏（任务书 §3.2.1）。硬编码以保持 analysis 独立于 client。
GOOD_TO_BAD_THRESHOLDS = (90, 80, 70, 60, 50, 40, 30, 20, 10)
# 好果消耗动作成本（任务书 §4/§5/§6）：供 good_fruit 支出归因
ACTION_GOOD_COST = {
    "CLEAR": 1,           # 主车队清障
    "RUSH_SPEED": 2,      # 疾行令
}
WINDOW_CARD_GOOD_COST = {"XIAN_GONG": 1}  # 献功耗 1 好果
STALL_STATES = ("MOVING", "WAITING")
STALL_MIN_LEN = 3        # 连续 ≥3 帧才记为卡死段（诊断阈值另设）


@dataclass
class StallSegment:
    start_round: int
    end_round: int
    node: Optional[str]
    state: str
    length: int


@dataclass
class FreshnessCross:
    round: int
    threshold: int
    fresh_before: float
    fresh_after: float


@dataclass
class BlockEncounter:
    node: str
    kind: str               # obstacle / guard
    owner: Optional[str]    # 设卡归属（guard 时）
    start_round: int
    end_round: Optional[int]
    resolution: Optional[str]   # CLEAR / BREAK_GUARD / FORCED_PASS / CLAIM_TASK / reroute / cleared / unknown
    duration: Optional[int]


@dataclass
class OffensiveGuard:
    node: str
    set_round: int
    extra_good: int
    reinforced: bool
    reinforce_round: Optional[int]
    opp_passed: bool            # 对手是否在种卡后占据过该节点
    opp_pass_round: Optional[int]
    cost_good: int              # extra_good（基础好果成本，key_pass=1 + extra）
    cost_frames: int            # 设卡处理 4 帧


@dataclass
class WindowRecord:
    contest_id: str
    type: Optional[str]
    rounds: list = field(default_factory=list)
    my_cards: list = field(default_factory=list)
    opp_cards: list = field(default_factory=list)
    my_final_pt: Optional[int] = None
    opp_final_pt: Optional[int] = None
    my_win: Optional[bool] = None
    net_good_cost: int = 0
    net_guard_cost: int = 0


@dataclass
class MatchMetrics:
    match_id: Optional[str] = None
    duration: int = 600

    # 交付
    delivered: bool = False
    deliver_round: Optional[int] = None
    fresh_at_deliver: Optional[float] = None
    good_fruit_at_deliver: Optional[int] = None
    task_score: Optional[int] = None
    bounty_score: Optional[int] = None
    total_score: Optional[int] = None
    i_won: Optional[bool] = None
    retired: bool = False

    # 鲜度
    fresh_traj: list = field(default_factory=list)     # (round, fresh)
    threshold_crosses: list = field(default_factory=list)
    good_fruit_start: int = 100
    good_fruit_loss_conversion: int = 0     # 转坏
    good_fruit_loss_spend: int = 0          # 动作消耗
    good_fruit_loss_total: int = 0
    good_fruit_loss_unattributed: int = 0

    # 卡死
    stalls: list = field(default_factory=list)

    # 阻塞
    encounters: list = field(default_factory=list)

    # 预算漂移
    budget_traj: list = field(default_factory=list)   # (round, est, left)
    est_over_left_max: int = 0            # max(est - left)，正=曾预测超时
    final_drift: Optional[int] = None     # deliver - (last_round + last_est)

    # 窗口
    windows: list = field(default_factory=list)

    # 进攻设卡
    guards: list = field(default_factory=list)

    # RUSH 时点
    rush_start_round: Optional[int] = None
    verify_start_round: Optional[int] = None
    verify_end_round: Optional[int] = None

    # 直方图
    action_hist: dict = field(default_factory=dict)
    none_heartbeat_ratio: Optional[float] = None
    reject_hist: dict = field(default_factory=dict)

    # 对手（若日志含 opp 镜像）
    opp_delivered: Optional[bool] = None
    opp_deliver_round: Optional[int] = None


def compute(trace: MatchTrace) -> MatchMetrics:
    m = MatchMetrics(match_id=trace.meta.match_id, duration=trace.meta.duration_round)
    _delivery(m, trace)
    _freshness(m, trace)
    _stalls(m, trace)
    _blocks(m, trace)
    _budget(m, trace)
    _windows(m, trace)
    _guards(m, trace)
    _rush(m, trace)
    _histograms(m, trace)
    _opponent(m, trace)
    return m


def _delivery(m, trace):
    me_score = next((s for s in trace.scores if s.me), None)
    if me_score:
        m.delivered = me_score.delivered
        m.deliver_round = me_score.deliver_round
        # fresh/good_fruit 仅在交付时有意义（未交付时 Score 行的 fresh 是终局值，不计）
        if me_score.delivered:
            m.fresh_at_deliver = me_score.fresh
            m.good_fruit_at_deliver = me_score.good_fruit
        m.task_score = me_score.task_score
        m.bounty_score = me_score.bounty_score
        m.total_score = me_score.total
        m.retired = me_score.retired
    if trace.over:
        m.i_won = trace.over.i_won


def _freshness(m, trace):
    prev = None
    for fr in trace.frames:
        if fr.fresh is None:
            continue
        m.fresh_traj.append((fr.round, fr.fresh))
        if prev is not None and fr.fresh < prev:
            for t in GOOD_TO_BAD_THRESHOLDS:
                if prev >= t > fr.fresh:
                    m.threshold_crosses.append(FreshnessCross(
                        round=fr.round, threshold=t,
                        fresh_before=prev, fresh_after=fr.fresh))
        prev = fr.fresh

    # 好果归因
    m.good_fruit_loss_conversion = len(m.threshold_crosses)
    spend = 0
    for a in trace.actions:
        if a.action in ACTION_GOOD_COST:
            spend += ACTION_GOOD_COST[a.action]
        if a.action == "SET_GUARD" and a.extra_good:
            spend += a.extra_good
        if a.action == "BREAK_GUARD" and a.good:
            spend += a.good
    # 窗口献功
    for c in trace.contests:
        if c.my_card in WINDOW_CARD_GOOD_COST:
            spend += WINDOW_CARD_GOOD_COST[c.my_card]
    m.good_fruit_loss_spend = spend
    if m.good_fruit_at_deliver is not None:
        m.good_fruit_loss_total = m.good_fruit_start - m.good_fruit_at_deliver
        m.good_fruit_loss_unattributed = m.good_fruit_loss_total \
            - m.good_fruit_loss_conversion - m.good_fruit_loss_spend


def _stalls(m, trace):
    """卡死段：连续 ≥STALL_MIN_LEN 帧 state∈{MOVING,WAITING} 且本帧动作为 NONE 且 node 未变。"""
    action_by_round = {}
    for a in trace.actions:
        if a.round is not None and a.round not in action_by_round:
            action_by_round[a.round] = a.action
    seg = None
    prev_node = None
    for fr in trace.frames:
        is_stall_frame = (
            fr.state in STALL_STATES
            and action_by_round.get(fr.round) in (None, "NONE")
            and (prev_node is None or fr.node == prev_node)
        )
        if is_stall_frame:
            if seg is None:
                seg = {"start": fr.round, "end": fr.round, "node": fr.node, "state": fr.state}
            else:
                seg["end"] = fr.round
        else:
            if seg is not None:
                _emit_stall(m, seg)
                seg = None
        prev_node = fr.node
    if seg is not None:
        _emit_stall(m, seg)


def _emit_stall(m, seg):
    length = (seg["end"] or 0) - (seg["start"] or 0) + 1
    if length >= STALL_MIN_LEN:
        m.stalls.append(StallSegment(
            start_round=seg["start"], end_round=seg["end"],
            node=seg["node"], state=seg["state"], length=length))


def _blocks(m, trace):
    """重建每个节点的阻塞 encounter：从首次出现到解除，归因解决方式。"""
    by_node = {}
    for b in trace.blocks:
        by_node.setdefault(b.node, []).append(b)
    # 动作索引：node -> [(round, action)]
    node_actions = {}
    for a in trace.actions:
        if a.target:
            node_actions.setdefault(a.target, []).append((a.round, a.action))

    for node, evs in by_node.items():
        evs.sort(key=lambda b: (b.round or 0))
        start = None
        kind = None
        owner = None
        for b in evs:
            if b.cleared:
                if start is not None:
                    resolution = _resolve_block(node, start, b.round, node_actions, evs)
                    m.encounters.append(BlockEncounter(
                        node=node, kind=kind or "obstacle", owner=owner,
                        start_round=start, end_round=b.round,
                        resolution=resolution,
                        duration=(b.round - start) if start and b.round else None))
                    start = None
                continue
            if start is None:
                start = b.round
                kind = "guard" if b.guard_owner else "obstacle"
                owner = b.guard_owner
            else:
                # 更新防守值变化但同一段
                if b.guard_owner:
                    owner = b.guard_owner
        # 未解除的尾段
        if start is not None:
            resolution = _resolve_block(node, start, None, node_actions, evs)
            m.encounters.append(BlockEncounter(
                node=node, kind=kind or "obstacle", owner=owner,
                start_round=start, end_round=None,
                resolution=resolution, duration=None))


def _resolve_block(node, start, end, node_actions, evs):
    """在 [start, end] 内对该节点采取的解决动作。"""
    acts = [(r, a) for r, a in node_actions.get(node, [])
            if r is not None and start is not None
            and r >= start and (end is None or r <= end)]
    for r, a in acts:
        if a == "CLEAR":
            return "CLEAR"
        if a == "BREAK_GUARD":
            return "BREAK_GUARD"
        if a == "FORCED_PASS":
            return "FORCED_PASS"
        if a == "CLAIM_TASK":
            return "CLAIM_TASK"
    if end is not None:
        return "cleared"
    # 未解除且无直接动作 → 可能绕行
    return "reroute"


def _budget(m, trace):
    for b in trace.budgets:
        if b.est is None or b.left is None:
            continue
        m.budget_traj.append((b.round, b.est, b.left))
        m.est_over_left_max = max(m.est_over_left_max, b.est - b.left)
    if m.budget_traj and m.deliver_round is not None:
        last_round, last_est, _ = m.budget_traj[-1]
        m.final_drift = m.deliver_round - (last_round + last_est)


def _windows(m, trace):
    by_id = {}
    for c in trace.contests:
        by_id.setdefault(c.contest_id, []).append(c)
    for cid, evs in by_id.items():
        evs.sort(key=lambda c: (c.round or 0))
        rec = WindowRecord(contest_id=cid, type=evs[0].type)
        for c in evs:
            if c.round is not None:
                rec.rounds.append(c.round)
            if c.my_card:
                rec.my_cards.append(c.my_card)
            if c.opp_card:
                rec.opp_cards.append(c.opp_card)
            rec.my_final_pt = c.my_pt if c.my_pt is not None else rec.my_final_pt
            rec.opp_final_pt = c.opp_pt if c.opp_pt is not None else rec.opp_final_pt
        if rec.my_final_pt is not None and rec.opp_final_pt is not None:
            if rec.my_final_pt >= 2:
                rec.my_win = True
            elif rec.opp_final_pt >= 2:
                rec.my_win = False
        rec.net_guard_cost = rec.my_cards.count("BING_ZHENG")
        rec.net_good_cost = rec.my_cards.count("XIAN_GONG")
        m.windows.append(rec)


def _guards(m, trace):
    """进攻设卡 ROI：每个 SET_GUARD → 是否增援/对手是否经过。"""
    set_actions = [a for a in trace.actions if a.action == "SET_GUARD"]
    reinforce = [a for a in trace.actions if a.action == "SQUAD_REINFORCE"]
    for a in set_actions:
        node = a.target
        if not node:
            continue
        reinforced = any(r.target == node and (r.round or 0) >= (a.round or 0) for r in reinforce)
        rein_round = next((r.round for r in reinforce
                           if r.target == node and (r.round or 0) >= (a.round or 0)), None)
        # 对手是否在种卡后占据过该节点
        opp_pass_round = None
        for fr in trace.frames:
            if (a.round is not None and fr.round is not None and fr.round > a.round
                    and fr.opp and fr.opp.node == node):
                opp_pass_round = fr.round
                break
        m.guards.append(OffensiveGuard(
            node=node, set_round=a.round or 0,
            extra_good=a.extra_good or 0,
            reinforced=reinforced, reinforce_round=rein_round,
            opp_passed=opp_pass_round is not None, opp_pass_round=opp_pass_round,
            cost_good=(a.extra_good or 0), cost_frames=4))


def _rush(m, trace):
    for fr in trace.frames:
        if m.rush_start_round is None and fr.phase == "RUSH":
            m.rush_start_round = fr.round
            break
    for fr in trace.frames:
        if fr.state == "VERIFYING" and m.verify_start_round is None:
            m.verify_start_round = fr.round
        if fr.verified and m.verify_end_round is None and m.verify_start_round is not None:
            m.verify_end_round = fr.round
            break


def _histograms(m, trace):
    hist = Counter(a.action for a in trace.actions if a.action)
    m.action_hist = dict(hist)
    total = sum(hist.values())
    none_count = hist.get("NONE", 0)
    m.none_heartbeat_ratio = (none_count / total) if total else None
    m.reject_hist = dict(Counter(r.code for r in trace.rejects if r.code))


def _opponent(m, trace):
    opp_score = next((s for s in trace.scores if not s.me), None)
    if opp_score:
        m.opp_delivered = opp_score.delivered
        m.opp_deliver_round = opp_score.deliver_round
