"""P3 §6.3 鲜度/资源 race 单测（默认关，本测显式打开开关验证行为）。

覆盖：鲜度劣势时提前用冰鉴(ENABLE_FRESHNESS_RACE)；资源 race 抢占对手争夺的路线附近冰鉴
(ENABLE_RESOURCE_DENY)——含对手不可达/抢不过/偏离过大/已足额/开关关闭的守卫。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from strategy.projection import OpponentEta  # noqa: E402

PID = 1001
OPP = 2002

# 线性：S01(me) - RN(冰鉴节点) - S15(终点)。各 ROAD dist10 = 14 帧。
SD = {"matchId": "fr", "durationRound": 600,
      "nodes": [{"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
                {"nodeId": "RN", "type": "STATION", "x": 1, "y": 0},
                {"nodeId": "S15", "type": "FINISH", "x": 2, "y": 0, "terminal": True}],
      "edges": [{"fromNodeId": "S01", "toNodeId": "RN", "routeType": "ROAD", "distance": 10, "bidirectional": True},
                {"fromNodeId": "RN", "toNodeId": "S15", "routeType": "ROAD", "distance": 10, "bidirectional": True}],
      "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
      "processNodes": []}


def _world(me_fresh=100.0, opp_fresh=100.0, me_ice=0, rn_ice=1):
    me = {"playerId": PID, "teamId": "RED", "state": "IDLE", "currentNodeId": "S01",
          "verified": True, "goodFruit": 100, "freshness": me_fresh,
          "resources": {"ICE_BOX": me_ice} if me_ice else {}}
    opp = {"playerId": OPP, "teamId": "BLUE", "state": "IDLE", "currentNodeId": "S15",
           "verified": False, "goodFruit": 100, "freshness": opp_fresh}
    nodes = [{"nodeId": "RN", "resourceStock": {"ICE_BOX": rn_ice} if rn_ice else {}}]
    return WorldState({"round": 30, "phase": "NORMAL", "players": [me, opp], "nodes": nodes}, PID, None)


class TestFreshnessRace(unittest.TestCase):
    def setUp(self):
        self._saved = config.ENABLE_FRESHNESS_RACE
        config.ENABLE_FRESHNESS_RACE = True

    def tearDown(self):
        config.ENABLE_FRESHNESS_RACE = self._saved

    def _rescue(self, me_fresh, opp_fresh, me_ice=1):
        eng = DecisionEngine(GameContext(PID, "RED", 0, SD))
        w = _world(me_fresh=me_fresh, opp_fresh=opp_fresh, me_ice=me_ice)
        a = eng._freshness_rescue(w, w.me)
        return a.get("action") if a else None

    def test_uses_ice_box_early_when_losing_race(self):
        # 常态阈值 78：鲜度 85 本不用；但对手 100 领先≥10 → 劣势 → 提前用(阈值 88)。
        self.assertEqual(self._rescue(me_fresh=85.0, opp_fresh=100.0), "USE_RESOURCE")

    def test_no_early_use_when_freshness_comparable(self):
        # 对手鲜度与我方相近(未拉开 10) → 不属劣势，鲜度 85 仍不提前用。
        self.assertIsNone(self._rescue(me_fresh=85.0, opp_fresh=88.0))

    def test_still_uses_below_normal_threshold(self):
        # 常态阈值内(70<78)无论 race 与否都用。
        self.assertEqual(self._rescue(me_fresh=70.0, opp_fresh=70.0), "USE_RESOURCE")

    def test_no_ice_box_no_action(self):
        self.assertIsNone(self._rescue(me_fresh=85.0, opp_fresh=100.0, me_ice=0))

    def test_flag_off_no_early_use(self):
        config.ENABLE_FRESHNESS_RACE = False
        self.assertIsNone(self._rescue(me_fresh=85.0, opp_fresh=100.0))


class TestResourceRace(unittest.TestCase):
    def setUp(self):
        self._saved = config.ENABLE_RESOURCE_DENY
        config.ENABLE_RESOURCE_DENY = True

    def tearDown(self):
        config.ENABLE_RESOURCE_DENY = self._saved

    def _engine(self, me_ice=0, eta_nodes=None):
        eng = DecisionEngine(GameContext(PID, "RED", 0, SD))
        eng.opponent_eta = OpponentEta("S15", None, None, dict(eta_nodes or {}), False, 0.8)
        return eng, GameMap(SD)

    def _race(self, eng, gm, me_ice=0, rn_ice=1):
        w = _world(me_ice=me_ice, rn_ice=rn_ice)
        return eng._maybe_resource_race(w, w.me, gm, "S01", "S15")

    def test_grabs_contested_ice_box(self):
        # 对手 ETA 到 RN=20，我方到 RN(14)≤20 → 抢占。
        eng, gm = self._engine(eta_nodes={"RN": 20})
        self.assertEqual(self._race(eng, gm, me_ice=0), "RN")

    def test_no_race_when_opponent_cannot_reach(self):
        eng, gm = self._engine(eta_nodes={})           # 无 RN ETA
        self.assertIsNone(self._race(eng, gm, me_ice=0))

    def test_no_race_when_cannot_beat_opponent(self):
        eng, gm = self._engine(eta_nodes={"RN": 10})   # 对手 10 < 我方 14
        self.assertIsNone(self._race(eng, gm, me_ice=0))

    def test_no_race_when_already_stocked(self):
        # 已达 RESOURCE_RACE_ICEBOX_KEEP(2) → 不为它绕路。
        eng, gm = self._engine(eta_nodes={"RN": 20})
        self.assertIsNone(self._race(eng, gm, me_ice=2))

    def test_flag_off_no_race(self):
        config.ENABLE_RESOURCE_DENY = False
        eng, gm = self._engine(eta_nodes={"RN": 20})
        self.assertIsNone(self._race(eng, gm, me_ice=0))


class TestRaceDefaultsOff(unittest.TestCase):
    def test_defaults(self):
        self.assertFalse(config.ENABLE_FRESHNESS_RACE)
        self.assertFalse(config.ENABLE_RESOURCE_DENY)

    def test_freshness_rescue_baseline_below_78(self):
        # 默认关：鲜度 85 不用冰鉴（仅常态 <78 才用），行为不变。
        eng = DecisionEngine(GameContext(PID, "RED", 0, SD))
        w = _world(me_fresh=85.0, opp_fresh=100.0, me_ice=1)
        self.assertIsNone(eng._freshness_rescue(w, w.me))


if __name__ == "__main__":
    unittest.main()
