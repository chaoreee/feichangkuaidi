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


class Projector:
    """构建 ProjectionBus。持有跨帧的 ModeMachine（滞后状态）。"""

    def __init__(self, ctx):
        self.ctx = ctx
        self.machine = ModeMachine(
            _cfg("LEAD_SAFE", 40),
            _cfg("MODE_HYSTERESIS_FRAMES", 5),
            _cfg("PROJECTION_MIN_CONFIDENCE", 0.55),
        )

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

        # 交付时鲜度与好果（跨 good→bad 阈值折损）粗估。
        frames_out = travel if travel != _INF else 0
        proj_fresh = max(0.0, pv.freshness - frames_out * AVG_FRESHNESS_LOSS_PER_FRAME)
        lost = len(rules.crossed_good_to_bad_thresholds(pv.freshness, proj_fresh))
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


def _cfg(name, default):
    import config
    return getattr(config, name, default)
