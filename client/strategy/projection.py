"""博弈投影层（Layer 1 投影总线 + §3.3 分数质量地板）。

见 docs/game_theory_projection_strategy.md。本模块是**纯观测基础设施**：

- `project_final_score`：复用 `core/rules.py` 纯函数，把一组投影字段组合成投影终局分。
- `net_score_delta`（§3.3, P1.5）：估算某个增量动作对投影终局分的净影响 ΔEV，
  供 Layer 2-4 的增量动作在执行前作分数质量守卫（与时间地板 `_can_afford` 组成与门）。
- `Projector`：每帧基于 `WorldState` 投影双方终局分/交付帧，计算分差与风险档位，
  产出只读的 `ProjectionBus`。它**不产生任何动作**——动作仍由现有策略函数输出。
- `ModeMachine`：带滞后（hysteresis）与低置信回落的风险档位状态机。

设计铁律（P1）：投影总线是只读输入，不改变任何动作输出；端到端行为与现状逐帧一致。
"""

import math
from dataclasses import dataclass, field
from enum import Enum

from core import rules

# 观测层近似常量：不含天气/急策的平均每帧移动鲜度损耗（~ROAD/WATER/MOUNTAIN 均值）。
# 用于粗估交付时鲜度与跨阈值转坏数；P1 只求可解释、可校准，不追求逐帧精确。
AVG_FRESHNESS_LOSS_PER_FRAME = 0.06

# 默认宫门验核耗时（gm.process_nodes 无 gate 信息时的回退）。
DEFAULT_VERIFY_FRAMES = 6

_INF = float("inf")


class RiskMode(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    EVEN = "EVEN"
    AGGRESSIVE = "AGGRESSIVE"


@dataclass(frozen=True)
class Projection:
    player_id: int
    deliver_frame: "int | None"
    projected_score: float
    projected_good_fruit: int
    projected_freshness: float
    projected_task_score: int
    projected_bounty_score: int
    route: tuple = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class ProjectionBus:
    my_projection: Projection
    opponent_projection: "Projection | None"
    gap: float
    mode: RiskMode
    reason: str


@dataclass(frozen=True)
class OpponentEta:
    """对手轨迹 ETA（P3 §6.1）：估算对手到宫门/终点/关键节点的帧数。

    只作为 tie-breaker 或争夺判断的**只读输入**，不直接产生动作。
    轨迹频繁变化时 confidence 下降（对手意图不可观测，见 §4.4）。
    """
    from_node: "str | None"          # 估算起算的对手参考节点（在途时为 next_node）
    to_gate: "int | None"
    to_finish: "int | None"          # 含未验核时的验核耗时
    to_nodes: dict = field(default_factory=dict)   # nodeId -> 预计到达帧数
    verified: bool = False
    confidence: float = 0.0

    def eta(self, node_id):
        """到指定节点的 ETA（帧），未知返回 None。"""
        return self.to_nodes.get(node_id)


# ---------------------------------------------------------------------------
# 投影分组合 + 分数质量地板（纯函数）
# ---------------------------------------------------------------------------

def project_final_score(deliver_frame, task_base, good_fruit, freshness,
                        raw_bounty=0, penalty=0, duration=600):
    """把投影字段组合成投影终局分（§4.2），完全复用 core/rules.py 的公式。

    deliver_frame 为 None 或超过 duration 视为未能交付：仅计未交付口径的
    任务分/悬赏分（无送达基础分/好果分/鲜度分/用时分），与规则一致。
    """
    delivered = deliver_frame is not None and deliver_frame <= duration
    if delivered:
        components = [
            rules.delivery_base_score(task_base),
            rules.good_fruit_score(good_fruit),
            rules.freshness_score(freshness),
            rules.time_score(deliver_frame, task_base),
            rules.task_score(task_base, delivered=True),
            rules.bounty_score(raw_bounty, delivered=True),
        ]
    else:
        components = [
            rules.task_score(task_base, delivered=False),
            rules.bounty_score(raw_bounty, delivered=False),
        ]
    return float(rules.total_score(components, penalty))


def net_score_delta(deliver_frame, task_base, good_fruit, freshness,
                    raw_bounty=0, penalty=0, duration=600,
                    extra_task_score=0, extra_bounty=0, extra_frames=0,
                    good_fruit_burned=0, extra_freshness_loss=0.0):
    """ΔEV = 投影分(采取动作) − 投影分(不采取动作)（§3.3, P1.5）。

    前六个参数是**不采取动作**时的投影基线字段；后五个是该增量动作带来的变化：
      - extra_task_score / extra_bounty：任务分 / 悬赏原始分增量（收益）
      - extra_frames：额外耗时（推迟交付帧 → 用时分下降）
      - good_fruit_burned：为攻坚/清障烧掉的好果（好果数量分下降）
      - extra_freshness_loss：额外鲜度损耗（鲜度分下降，可能跨阈值再触发转坏）

    返回净收益（浮点，可正可负）。纯函数、无副作用，便于单测。
    调用方据此做与门：`_can_afford(...) and net_score_delta(...) >= threshold`。
    """
    base = project_final_score(
        deliver_frame, task_base, good_fruit, freshness, raw_bounty, penalty, duration)

    new_deliver = None if deliver_frame is None else deliver_frame + extra_frames
    new_fresh = max(0.0, freshness - extra_freshness_loss)
    # 额外鲜度损耗跨过 good→bad 阈值也会再折损好果。
    crossed = len(rules.crossed_good_to_bad_thresholds(freshness, new_fresh))
    new_good = max(0, good_fruit - good_fruit_burned - crossed)

    after = project_final_score(
        new_deliver, task_base + extra_task_score, new_good, new_fresh,
        raw_bounty + extra_bounty, penalty, duration)
    return after - base


# ---------------------------------------------------------------------------
# 风险档位状态机（滞后 + 低置信回落）
# ---------------------------------------------------------------------------

class ModeMachine:
    """gap→mode 状态机。切档需连续 hysteresis_frames 帧同向；低置信回落 EVEN。"""

    def __init__(self, lead_safe, hysteresis_frames, min_confidence):
        self.lead_safe = lead_safe
        self.hysteresis_frames = max(1, hysteresis_frames)
        self.min_confidence = min_confidence
        self.mode = RiskMode.EVEN
        self._candidate = RiskMode.EVEN
        self._streak = 0

    def _target(self, gap, confidence):
        if confidence < self.min_confidence:
            return RiskMode.EVEN, "low_confidence"
        if gap > self.lead_safe:
            return RiskMode.CONSERVATIVE, "gap_above_threshold"
        if gap < -self.lead_safe:
            return RiskMode.AGGRESSIVE, "gap_below_threshold"
        return RiskMode.EVEN, "gap_within_band"

    def update(self, gap, confidence):
        """返回 (mode, changed, from_mode, reason)。"""
        target, reason = self._target(gap, confidence)
        if target == self.mode:
            self._candidate = target
            self._streak = 0
            return self.mode, False, self.mode, reason
        if target == self._candidate:
            self._streak += 1
        else:
            self._candidate = target
            self._streak = 1
        if self._streak >= self.hysteresis_frames:
            from_mode = self.mode
            self.mode = target
            self._candidate = target
            self._streak = 0
            return self.mode, True, from_mode, reason
        return self.mode, False, self.mode, reason


# ---------------------------------------------------------------------------
# 投影器：每帧构建投影总线
# ---------------------------------------------------------------------------

def _verify_frames(gm):
    info = gm.process_nodes.get(gm.gate_node) if gm.gate_node else None
    return (info.get("processRound") if info else DEFAULT_VERIFY_FRAMES) or DEFAULT_VERIFY_FRAMES


def freshness_loss_for_path(gm, path, weather_coef=1.0, verify_frames=0):
    """按路线类型逐边累计交付路径的鲜度损耗（替换 AVG_FRESHNESS_LOSS_PER_FRAME 平摊）。

    移动帧：FRESHNESS_LOSS_MOVE[route_type] × frames_on_edge；停靠帧（途经固定处理站）：
    FRESHNESS_LOSS_BASE × processRound；宫门验核停靠：FRESHNESS_LOSS_BASE × verify_frames
    （验核帧由调用方按是否已验核传入，gate 本身在处理站循环里排除避免重复）。均乘天气鲜度系数。

    永不抛出：path 空/单点、edge 缺失、processRound 缺失均安全跳过。属观测层近似——天气用当前
    快照系数（不预测未来天气窗口），急策系数不计（RUSH_PROTECT 仅终局触发且 0.2 会过度抵免）。
    """
    if not path or len(path) < 2:
        return max(0.0, verify_frames) * rules.FRESHNESS_LOSS_BASE * weather_coef
    loss = 0.0
    gate = gm.gate_node
    # 移动损耗 + 途经处理站停靠损耗（gate 排除，由 verify_frames 单独计）
    for i in range(len(path) - 1):
        e = gm.edge_between(path[i], path[i + 1])
        if e is not None:
            base = rules.FRESHNESS_LOSS_MOVE.get(e.route_type, rules.FRESHNESS_LOSS_BASE)
            fr = rules.frames_on_edge(e.distance, e.route_type)
            loss += fr * base * weather_coef
        mid = path[i] if i > 0 else None
        if mid and mid != gate and mid in gm.process_nodes:
            pr = (gm.process_nodes[mid].get("processRound") or 0)
            loss += pr * rules.FRESHNESS_LOSS_BASE * weather_coef
    loss += max(0.0, verify_frames) * rules.FRESHNESS_LOSS_BASE * weather_coef
    return loss



class Projector:
    """构建 ProjectionBus。持有跨帧的 ModeMachine（滞后状态）。"""

    def __init__(self, ctx):
        self.ctx = ctx
        self.machine = ModeMachine(
            _cfg("LEAD_SAFE", 40),
            _cfg("MODE_HYSTERESIS_FRAMES", 5),
            _cfg("PROJECTION_MIN_CONFIDENCE", 0.55),
        )
        # P3 §6.1：对手轨迹稳定性跟踪（原地改目标视为路线变更 → 降低 ETA 置信）。
        self._opp_prev = None
        self._opp_route_changes = 0.0

    def build(self, world):
        """返回 (bus, changed, from_mode)。任何缺信息都安全降级，绝不抛出。"""
        gm = self.ctx.game_map
        terminal = gm.terminal_nodes[0] if (gm and gm.terminal_nodes) else None
        rnd = world.round or 0

        my = self._project_player(world, world.me, gm, terminal, rnd, is_me=True)
        opp = self._project_player(world, world.opponent, gm, terminal, rnd, is_me=False)

        if my is not None and opp is not None:
            gap = my.projected_score - opp.projected_score
            confidence = opp.confidence
        else:
            gap = 0.0
            confidence = 0.0

        mode, changed, from_mode, reason = self.machine.update(gap, confidence)
        # my 缺失（尚未拿到本方位置）时给一个占位投影，保证 bus 字段完整。
        if my is None:
            my = Projection(self.ctx.player_id, None, 0.0, 0, 0.0, 0, 0, (), 0.0)
        return ProjectionBus(my, opp, gap, mode, reason), changed, from_mode

    def _project_player(self, world, pv, gm, terminal, rnd, is_me):
        if pv is None or gm is None or terminal is None:
            return None
        ref = pv.current_node_id or pv.next_node_id
        if not ref:
            return None

        travel = self._deliver_travel(gm, ref, terminal, pv.verified)
        if travel == _INF:
            deliver_frame = None
        else:
            deliver_frame = rnd + travel

        # 交付时鲜度与好果（跨 good→bad 阈值折损）：按路线类型逐边累计损耗（替换 0.06 平摊）。
        path, _ = gm.time_optimal_path(ref, terminal)
        wcoef = rules.FRESHNESS_WEATHER_COEF.get(world.active_weather_type(), 1.0) \
            if world.active_weather_type() else 1.0
        vframes = 0 if pv.verified else _verify_frames(gm)
        loss = freshness_loss_for_path(gm, path, wcoef, verify_frames=vframes) \
            if travel != _INF else 0.0
        proj_fresh = max(0.0, (pv.freshness or 0.0) - loss)
        lost = len(rules.crossed_good_to_bad_thresholds(pv.freshness or 0.0, proj_fresh))
        proj_good = max(0, (pv.good_fruit or 0) - lost)

        task_base = pv.task_score or 0
        raw_bounty = 0  # 悬赏投影属 Layer 2/3；P1 两侧同置 0，保持对称且保守。
        penalty = pv.penalty_score or 0

        score = project_final_score(
            deliver_frame, task_base, proj_good, proj_fresh, raw_bounty, penalty,
            self.ctx.duration_round or 600)

        confidence = 0.9 if is_me else self._opp_confidence(pv, rnd)
        return Projection(
            player_id=pv.player_id,
            deliver_frame=deliver_frame,
            projected_score=score,
            projected_good_fruit=proj_good,
            projected_freshness=proj_fresh,
            projected_task_score=task_base,
            projected_bounty_score=rules.bounty_score(raw_bounty, delivered=deliver_frame is not None),
            route=(ref, terminal),
            confidence=confidence,
        )

    def _deliver_travel(self, gm, node, terminal, verified):
        _, travel = gm.time_optimal_path(node, terminal)
        if travel == _INF:
            return _INF
        est = travel
        if not verified:
            est += _verify_frames(gm)
        return est

    def _opp_confidence(self, pv, rnd):
        """对手投影置信度（§4.4）：位置可见但意图不可观测。

        前中段噪声大→偏低，越临近终局路线收敛→越可信。mode 主战场在中后段。
        """
        if not (pv.current_node_id or pv.next_node_id):
            return 0.1
        duration = self.ctx.duration_round or 600
        conf = 0.30 + (rnd / duration) * 0.55
        return max(0.0, min(0.90, conf))

    # ---- 对手轨迹 ETA（P3 §6.1，纯观测）----

    def build_opponent_eta(self, world):
        """估算对手到宫门/终点/任务点/资源点的帧数。异常安全，绝不抛出。

        在途（move_progress∈(0,1)）时以 next_node 起算并加到 next 的残余帧（§4.3 保守口径）。
        未验核时 to_finish 计入验核耗时。ETA 只作 tie-breaker/争夺判断输入。
        """
        gm = self.ctx.game_map
        opp = world.opponent
        self._track_opp_route(opp)
        if opp is None or gm is None:
            return OpponentEta(None, None, None, {}, False, 0.0)
        base, offset = self._eta_base(gm, opp)
        if not base:
            return OpponentEta(None, None, None, {}, bool(opp.verified), 0.1)

        gate = gm.gate_node
        terminal = gm.terminal_nodes[0] if gm.terminal_nodes else None
        to_gate = self._eta_to(gm, base, offset, gate) if gate else None
        to_finish = self._eta_to(gm, base, offset, terminal) if terminal else None
        if to_finish is not None and not opp.verified:
            to_finish += _verify_frames(gm)

        to_nodes = {}
        for nid in self._eta_targets(world):
            e = self._eta_to(gm, base, offset, nid)
            if e is not None:
                to_nodes[nid] = e

        return OpponentEta(base, to_gate, to_finish, to_nodes,
                           bool(opp.verified), self._eta_confidence(opp, world))

    def _eta_base(self, gm, opp):
        """返回 (base_node, offset)：对手后续路径的起算节点与已在途的残余帧数。"""
        cur, nxt = opp.current_node_id, opp.next_node_id
        prog = opp.move_progress or 0.0
        if nxt and cur and 0.0 < prog < 1.0:
            e = gm.edge_between(cur, nxt)
            if e is not None:
                total = rules.frames_on_edge(e.distance, e.route_type)
                if total != _INF:
                    return (nxt, max(0, math.ceil(total * (1.0 - prog))))
            return (nxt, 0)
        return (cur or nxt, 0)

    def _eta_to(self, gm, base, offset, target):
        if not target:
            return None
        if base == target:
            return offset
        _, travel = gm.time_optimal_path(base, target)
        if travel == _INF:
            return None
        return offset + travel

    def _eta_targets(self, world):
        """关注的到达点：活跃任务节点 + 有库存的资源节点（有界集合）。"""
        targets = set()
        for t in world.active_tasks():
            nid = t.get("nodeId")
            if nid:
                targets.add(nid)
        for nid, ns in world.node_states.items():
            if ns.resource_stock:
                targets.add(nid)
        return targets

    def _eta_confidence(self, opp, world):
        """§6.1：位置可见→随终局上升；轨迹频繁变化(原地改目标)→按变更计数打折。"""
        if not (opp.current_node_id or opp.next_node_id):
            return 0.1
        rnd = world.round or 0
        duration = self.ctx.duration_round or 600
        conf = (0.30 + (rnd / duration) * 0.55) / (1.0 + 0.5 * self._opp_route_changes)
        return max(0.0, min(0.90, conf))

    def _track_opp_route(self, opp):
        cur = opp.current_node_id if opp else None
        nxt = opp.next_node_id if opp else None
        if self._opp_prev is not None:
            pcur, pnxt = self._opp_prev
            if cur == pcur and pnxt and nxt and nxt != pnxt:
                self._opp_route_changes += 1.0          # 原地改目标 = 路线变更
            else:
                self._opp_route_changes = max(0.0, self._opp_route_changes - 0.25)  # 缓慢衰减
        self._opp_prev = (cur, nxt)


def _cfg(name, default):
    import config
    return getattr(config, name, default)
