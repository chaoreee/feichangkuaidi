"""P2 §5.3 终局交付 race 单测。

covers：对手将在窗口内交付且我方也接近时——落后/接近放宽疾行门槛抢交付帧、
领先抑制疾行(留急策护果)、鲜度危急不疾行；非 race 保持原有"远离终点才疾行"门槛。
直接构造 ProjectionBus 以精确控制 gap 与双方交付帧。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from strategy.projection import Projection, ProjectionBus, RiskMode  # noqa: E402

PID = 1001
OPP = 2002


def _node(nid, typ="STATION", start=False, terminal=False):
    return {"nodeId": nid, "type": typ, "x": 0, "y": 0, "start": start, "terminal": terminal}


def _edge(a, b, dist=10):
    return {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": dist, "bidirectional": True}


# 线性：S01 -[50]- SB -[10]- S14(gate) -[10]- S15(term)
# SB→S15 距离 20 ≤30（近）；S01→S15 距离 70 >30（远）。
SD = {"matchId": "r", "durationRound": 600,
      "nodes": [_node("S01", "START", start=True), _node("SB"),
                _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
      "edges": [_edge("S01", "SB", 50), _edge("SB", "S14"), _edge("S14", "S15")],
      "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14",
                                     "terminalNodeIds": ["S15"]}}},
      "processNodes": []}


def _world(node, fresh=100.0, phase="RUSH", resources=None, rnd=560, rush_used=0):
    inquire = {"round": rnd, "phase": phase,
               "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE",
                            "currentNodeId": node, "verified": True, "goodFruit": 100,
                            "freshness": fresh, "resources": resources or {},
                            "rushTacticUsedCount": rush_used}]}
    return WorldState(inquire, PID, None)


def _bus(gap, my_deliver, opp_deliver):
    my = Projection(PID, my_deliver, 500.0, 100, 100.0, 60, 0, (), 0.9)
    opp = Projection(OPP, opp_deliver, 500.0, 100, 100.0, 60, 0, (), 0.85)
    return ProjectionBus(my, opp, gap, RiskMode.EVEN, "test")


class TestEndgameRace(unittest.TestCase):
    def setUp(self):
        self.gm = GameMap(SD)
        self.eng = DecisionEngine(GameContext(PID, "RED", 0, SD))

    def _speed(self, node):
        return self.eng._rush_speed_warranted(self._w, self._w.me, self.gm, node, "S15")

    def test_racing_behind_close_sprints(self):
        # SB 近终点(距 20≤30)：非 race 本不疾行；race 落后 → 放宽门槛抢交付帧。
        self._w = _world("SB")
        self.eng.projection_bus = _bus(gap=-30, my_deliver=575, opp_deliver=572)
        self.assertEqual(self._speed("SB"), {"action": "RUSH_SPEED"})

    def test_non_racing_close_no_sprint(self):
        # 同样近终点，但对手不在窗口内交付（非 race）→ 保持原门槛：近则不疾行。
        self._w = _world("SB")
        self.eng.projection_bus = _bus(gap=-30, my_deliver=575, opp_deliver=595)
        self.assertIsNone(self._speed("SB"))

    def test_racing_leading_suppresses_sprint(self):
        # S01 远终点(距 70>30)：非 race 本会疾行；race 领先 → 抑制疾行(留急策护果)。
        self._w = _world("S01")
        self.eng.projection_bus = _bus(gap=30, my_deliver=575, opp_deliver=572)
        self.assertIsNone(self._speed("S01"))

    def test_non_racing_far_preserves_original_sprint(self):
        # 远终点、非 race → 维持原有"远且健康无马即疾行"。
        self._w = _world("S01")
        self.eng.projection_bus = _bus(gap=30, my_deliver=575, opp_deliver=595)
        self.assertEqual(self._speed("S01"), {"action": "RUSH_SPEED"})

    def test_freshness_critical_no_sprint_even_racing(self):
        # 落后 race 但鲜度危急(<90)：不疾行(+25%损耗雪上加霜)，交由护果令处理。
        self._w = _world("SB", fresh=80.0)
        self.eng.projection_bus = _bus(gap=-30, my_deliver=575, opp_deliver=572)
        self.assertIsNone(self._speed("SB"))

    def test_horse_blocks_sprint_even_racing(self):
        self._w = _world("SB", resources={"FAST_HORSE": 1})
        self.eng.projection_bus = _bus(gap=-30, my_deliver=575, opp_deliver=572)
        self.assertIsNone(self._speed("SB"))


class TestEndgameRaceState(unittest.TestCase):
    def setUp(self):
        self.eng = DecisionEngine(GameContext(PID, "RED", 0, SD))

    def test_detects_race_and_behind(self):
        self.eng.projection_bus = _bus(gap=-30, my_deliver=575, opp_deliver=572)
        self.assertEqual(self.eng._endgame_race_state(_world("SB"), _world("SB").me),
                         (True, True))

    def test_detects_race_and_leading(self):
        self.eng.projection_bus = _bus(gap=30, my_deliver=575, opp_deliver=572)
        self.assertEqual(self.eng._endgame_race_state(_world("SB"), _world("SB").me),
                         (True, False))

    def test_not_racing_when_opponent_far(self):
        self.eng.projection_bus = _bus(gap=-30, my_deliver=575, opp_deliver=595)
        racing, _ = self.eng._endgame_race_state(_world("SB"), _world("SB").me)
        self.assertFalse(racing)

    def test_not_racing_outside_rush_phase(self):
        self.eng.projection_bus = _bus(gap=-30, my_deliver=575, opp_deliver=572)
        w = _world("SB", phase="NORMAL")
        self.assertEqual(self.eng._endgame_race_state(w, w.me), (False, False))

    def test_not_racing_without_opponent_projection(self):
        my = Projection(PID, 575, 500.0, 100, 100.0, 60, 0, (), 0.9)
        self.eng.projection_bus = ProjectionBus(my, None, 0.0, RiskMode.EVEN, "no_opp")
        self.assertEqual(self.eng._endgame_race_state(_world("SB"), _world("SB").me),
                         (False, False))


if __name__ == "__main__":
    unittest.main()
