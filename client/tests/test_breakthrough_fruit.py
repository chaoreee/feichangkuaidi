"""P2 §5.1 行3 突破烧好果意愿单测。

covers：CONSERVATIVE 领先锁好果——负担得起时间税则突破优先 FORCED_PASS(障碍/敌卡)、
负担不起则回退烧好果保交付；EVEN/AGGRESSIVE 保持烧好果攻坚；档位映射与时间税估算。
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


# S01(起点) - SX(阻挡：障碍或敌卡) - S15(终点)
SD = {"matchId": "bt", "durationRound": 600,
      "nodes": [_node("S01", "START", start=True), _node("SX"), _node("S15", "FINISH", terminal=True)],
      "edges": [_edge("S01", "SX"), _edge("SX", "S15")],
      "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
      "processNodes": []}


def _world(obstacle=False, guard=None, good=100, rnd=20):
    nodes = []
    ns = {"nodeId": "SX"}
    if obstacle:
        ns["hasObstacle"] = True
    if guard:
        ns["guard"] = {"active": True, "defense": guard, "ownerTeamId": "BLUE"}
    if obstacle or guard:
        nodes.append(ns)
    inquire = {"round": rnd, "phase": "NORMAL",
               "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE",
                            "currentNodeId": "S01", "verified": True, "goodFruit": good,
                            "badFruit": 0, "freshness": 100.0}],
               "nodes": nodes}
    return WorldState(inquire, PID, None)


def _break(mode, **kw):
    gm = GameMap(SD)
    eng = DecisionEngine(GameContext(PID, "RED", 0, SD))
    eng.tuning = tuning_for_mode(mode)
    w = _world(**kw)
    return eng._breakthrough(w, w.me, gm, "SX", "S15")[0].get("action")


class TestBreakthroughFruit(unittest.TestCase):
    # ---- 障碍 ----
    def test_conservative_forced_pass_obstacle(self):
        self.assertEqual(_break(RiskMode.CONSERVATIVE, obstacle=True), "FORCED_PASS")

    def test_even_clears_obstacle(self):
        self.assertEqual(_break(RiskMode.EVEN, obstacle=True), "CLEAR")

    def test_aggressive_clears_obstacle(self):
        self.assertEqual(_break(RiskMode.AGGRESSIVE, obstacle=True), "CLEAR")

    # ---- 敌卡 ----
    def test_conservative_forced_pass_guard(self):
        self.assertEqual(_break(RiskMode.CONSERVATIVE, guard=2), "FORCED_PASS")

    def test_even_breaks_guard(self):
        self.assertEqual(_break(RiskMode.EVEN, guard=2), "BREAK_GUARD")

    # ---- 交付安全回退 ----
    def test_conservative_falls_back_to_clear_when_tax_unaffordable(self):
        # 逼近 600 帧：强制通行时间税会误期 → CONSERVATIVE 也回退烧好果攻坚保交付。
        self.assertEqual(_break(RiskMode.CONSERVATIVE, obstacle=True, rnd=595), "CLEAR")

    def test_conservative_forced_pass_when_time_ample(self):
        self.assertEqual(_break(RiskMode.CONSERVATIVE, obstacle=True, rnd=20), "FORCED_PASS")


class TestTuningRow3(unittest.TestCase):
    def test_flag_per_mode(self):
        self.assertTrue(tuning_for_mode(RiskMode.CONSERVATIVE).protect_good_fruit_on_breakthrough)
        self.assertFalse(tuning_for_mode(RiskMode.EVEN).protect_good_fruit_on_breakthrough)
        self.assertFalse(tuning_for_mode(RiskMode.AGGRESSIVE).protect_good_fruit_on_breakthrough)


class TestForcedPassTax(unittest.TestCase):
    def setUp(self):
        self.gm = GameMap(SD)
        self.eng = DecisionEngine(GameContext(PID, "RED", 0, SD))

    def test_obstacle_uses_fixed_tax(self):
        from core import rules
        w = _world(obstacle=True)
        self.assertEqual(self.eng._forced_pass_tax(w, self.gm, "SX"), rules.OBSTACLE_TIME_TAX)

    def test_guard_uses_defense_scaled_tax(self):
        from core import rules
        w = _world(guard=3)
        # 普通节点敌卡：min(40, 10 + defense*5)。
        self.assertEqual(self.eng._forced_pass_tax(w, self.gm, "SX"),
                         rules.guard_time_tax("normal", 3))


if __name__ == "__main__":
    unittest.main()
