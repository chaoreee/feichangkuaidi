"""P2 档位调参接入决策的行为单测（§5.1 行1/2/4 + §3.3 ΔEV 地板）。

覆盖：三档绕路上限/任务目标差异、AGGRESSIVE 放宽绕路上限、ΔEV 地板拒绝低价值绕路、
RUSH_PROTECT 阈值按档位。均直接驱动 DecisionEngine，验证"接入决策"生效。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from strategy.projection import RiskMode  # noqa: E402
from strategy.tuning import tuning_for_mode  # noqa: E402

PID = 1001


def _node(nid, typ="STATION", start=False, terminal=False):
    return {"nodeId": nid, "type": typ, "x": 0, "y": 0, "start": start, "terminal": terminal}


def _edge(a, b, dist=10):
    return {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": dist, "bidirectional": True}


def _diamond(spur_dist):
    """S01→SA→SJ→S15 与 S01→ST→SJ→S15 两条等距路；ST 在路上，绕去它额外帧≈0。"""
    return {
        "matchId": "w", "durationRound": 600,
        "nodes": [_node("S01", "START", start=True), _node("SA"), _node("ST"),
                  _node("SJ"), _node("S15", "FINISH", terminal=True)],
        "edges": [_edge("S01", "SA"), _edge("SA", "SJ"), _edge("SJ", "S15"),
                  _edge("S01", "ST", spur_dist), _edge("ST", "SJ")],
        "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
        "processNodes": [],
    }


def _spur(st_dist):
    """S01→SA→SJ→S15 为直达；ST 是挂在 SJ 上的死胡同任务点，绕去它需往返，额外帧≈2×(SJ↔ST)。"""
    return {
        "matchId": "w", "durationRound": 600,
        "nodes": [_node("S01", "START", start=True), _node("SA"), _node("SJ"),
                  _node("ST"), _node("S15", "FINISH", terminal=True)],
        "edges": [_edge("S01", "SA"), _edge("SA", "SJ"), _edge("SJ", "S15"),
                  _edge("SJ", "ST", st_dist)],
        "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
        "processNodes": [],
    }


def _world(sd, gm, task_score=0, task_pts=30, fresh=100.0):
    inquire = {
        "round": 20, "phase": "NORMAL",
        "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE", "currentNodeId": "S01",
                     "verified": False, "goodFruit": 100, "freshness": fresh, "taskScore": task_score}],
        "tasks": [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "ST", "score": task_pts,
                   "processRound": 0, "active": True, "completed": False}],
        "nodes": [], "events": [],
    }
    return WorldState(inquire, PID, gm)


def _engine(sd, world):
    gm = GameMap(sd)
    eng = DecisionEngine(GameContext(PID, "RED", 0, sd))
    eng.decide(world)  # 填充 projection_bus + tuning(EVEN)
    return eng, gm


def _detour(eng, gm, world, mode):
    eng.tuning = tuning_for_mode(mode)
    return eng._task_detour_target(world, world.me, gm, "S01", "S15")


class TestModeDrivenDetour(unittest.TestCase):
    def test_even_takes_close_scored_task(self):
        sd = _diamond(10)  # 等距旁路，extra≈0
        w = _world(sd, GameMap(sd), task_pts=30)
        eng, gm = _engine(sd, w)
        self.assertEqual(_detour(eng, gm, w, RiskMode.EVEN), "ST")

    def test_conservative_disables_detour(self):
        # CONSERVATIVE task_seek_target=0：领先时不为任务绕路。
        sd = _diamond(10)
        w = _world(sd, GameMap(sd), task_pts=30)
        eng, gm = _engine(sd, w)
        self.assertIsNone(_detour(eng, gm, w, RiskMode.CONSERVATIVE))

    def test_aggressive_allows_detour_beyond_even_cap(self):
        # 死胡同旁路 extra≈76，落在 EVEN 上限(70)与 AGGRESSIVE 上限(90)之间。
        sd = _spur(27)
        w = _world(sd, GameMap(sd), task_pts=30)
        eng, gm = _engine(sd, w)
        even = _detour(eng, gm, w, RiskMode.EVEN)
        aggr = _detour(eng, gm, w, RiskMode.AGGRESSIVE)
        self.assertIsNone(even)          # 超 EVEN 绕路上限
        self.assertEqual(aggr, "ST")     # AGGRESSIVE 放宽上限后可取

    def test_delta_floor_rejects_low_value_detour(self):
        # 中等往返绕路(extra≈56<70)：高价值任务(30)取；同图仅把任务分值降到 1 → ΔEV 转负被拒。
        sd = _spur(20)
        eng_hi, gm_hi = _engine(sd, _world(sd, GameMap(sd), task_pts=30))
        w_hi = _world(sd, gm_hi, task_pts=30)
        self.assertEqual(_detour(eng_hi, gm_hi, w_hi, RiskMode.EVEN), "ST")

        eng_lo, gm_lo = _engine(sd, _world(sd, GameMap(sd), task_pts=1))
        w_lo = _world(sd, gm_lo, task_pts=1)
        self.assertIsNone(_detour(eng_lo, gm_lo, w_lo, RiskMode.EVEN))

    def test_aggressive_floor_still_rejects_net_negative(self):
        # 铁律：AGGRESSIVE 放宽绕路上限，但净负分（低价值远绕路）仍被 ΔEV 地板拒。
        sd = _spur(20)
        w = _world(sd, GameMap(sd), task_pts=1)
        eng, gm = _engine(sd, w)
        self.assertIsNone(_detour(eng, gm, w, RiskMode.AGGRESSIVE))


class TestRushProtectTiming(unittest.TestCase):
    """§5.1 行4：护果令阈值随档位；AGGRESSIVE 更克制。"""

    def _rush_world(self, gm, fresh):
        inquire = {"round": 560, "phase": "RUSH",
                   "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE",
                                "currentNodeId": "S14", "verified": True, "goodFruit": 100,
                                "freshness": fresh, "rushTacticUsedCount": 0}]}
        return WorldState(inquire, PID, gm)

    def setUp(self):
        self.sd = _diamond(10)
        self.gm = GameMap(self.sd)
        self.eng = DecisionEngine(GameContext(PID, "RED", 0, self.sd))

    def test_even_uses_rush_protect_below_90(self):
        self.eng.tuning = tuning_for_mode(RiskMode.EVEN)
        w = self._rush_world(self.gm, fresh=85.0)  # <90
        self.assertEqual(self.eng._maybe_rush_protect(w, w.me), {"action": "RUSH_PROTECT"})

    def test_aggressive_holds_rush_protect_at_85(self):
        # AGGRESSIVE 阈值 75：鲜度 85 尚不危急 → 不用护果令（把急策留给冲刺）。
        self.eng.tuning = tuning_for_mode(RiskMode.AGGRESSIVE)
        w = self._rush_world(self.gm, fresh=85.0)
        self.assertIsNone(self.eng._maybe_rush_protect(w, w.me))

    def test_aggressive_uses_rush_protect_when_critical(self):
        self.eng.tuning = tuning_for_mode(RiskMode.AGGRESSIVE)
        w = self._rush_world(self.gm, fresh=70.0)  # <75 危急
        self.assertEqual(self.eng._maybe_rush_protect(w, w.me), {"action": "RUSH_PROTECT"})


if __name__ == "__main__":
    unittest.main()
