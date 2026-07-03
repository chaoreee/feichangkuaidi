"""P3 §6.2 任务 race 单测（默认关，本测显式打开开关验证行为）。

覆盖：追平(对手≥阈值且我方<90 放宽任务目标/上限)、deny(抢占对手正奔赴且能更早到达、
跨对手里程碑的关键任务点)；各自的守卫（开关、里程碑、ETA 抢不过、可领取性）与不改基线。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from strategy.projection import Projection, ProjectionBus, OpponentEta, RiskMode  # noqa: E402
from strategy.tuning import tuning_for_mode  # noqa: E402

PID = 1001
OPP = 2002

# 线性：S01(me 起点) - TN(任务点) - S15(终点)。各 ROAD dist10 = 14 帧。
SD = {"matchId": "tr", "durationRound": 600,
      "nodes": [{"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
                {"nodeId": "TN", "type": "STATION", "x": 1, "y": 0},
                {"nodeId": "S15", "type": "FINISH", "x": 2, "y": 0, "terminal": True}],
      "edges": [{"fromNodeId": "S01", "toNodeId": "TN", "routeType": "ROAD", "distance": 10, "bidirectional": True},
                {"fromNodeId": "TN", "toNodeId": "S15", "routeType": "ROAD", "distance": 10, "bidirectional": True}],
      "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
      "processNodes": []}

TASK = {"taskId": "TK", "taskTemplateId": "T01", "nodeId": "TN", "score": 30,
        "processRound": 0, "active": True, "completed": False}


def _world(me_task=30, opp_task=85, tasks=None, task_owner=0, task_prot=0):
    t = dict(TASK)
    if task_owner:
        t["ownerPlayerId"] = task_owner
    if task_prot:
        t["protectionPlayerId"] = task_prot
    me = {"playerId": PID, "teamId": "RED", "state": "IDLE", "currentNodeId": "S01",
          "verified": True, "goodFruit": 100, "freshness": 100.0, "taskScore": me_task}
    opp = {"playerId": OPP, "teamId": "BLUE", "state": "IDLE", "currentNodeId": "S15",
           "verified": False, "goodFruit": 100, "freshness": 100.0, "taskScore": opp_task}
    inquire = {"round": 30, "phase": "NORMAL", "players": [me, opp],
               "tasks": tasks if tasks is not None else [t]}
    return WorldState(inquire, PID, None)


def _bus(my_task=90):
    my = Projection(PID, 100, 500.0, 100, 100.0, my_task, 0, (), 0.9)
    opp = Projection(OPP, 120, 400.0, 100, 100.0, 60, 0, (), 0.85)
    return ProjectionBus(my, opp, 100.0, RiskMode.EVEN, "t")


def _engine(mode=RiskMode.EVEN, my_task=90, eta_nodes=None):
    eng = DecisionEngine(GameContext(PID, "RED", 0, SD))
    eng.tuning = tuning_for_mode(mode)
    eng.projection_bus = _bus(my_task)
    eng.opponent_eta = OpponentEta("S15", None, None, dict(eta_nodes or {}), False, 0.8)
    return eng, GameMap(SD)


class TestCatchUp(unittest.TestCase):
    def setUp(self):
        self._saved = config.ENABLE_TASK_RACE
        config.ENABLE_TASK_RACE = True

    def tearDown(self):
        config.ENABLE_TASK_RACE = self._saved

    def test_catch_up_overrides_conservative_no_detour(self):
        # CONSERVATIVE 本不绕路(target 0)；追平(对手 85≥80、我方 30<90) → 放宽后绕去任务点。
        eng, gm = _engine(RiskMode.CONSERVATIVE, my_task=30)
        w = _world(me_task=30, opp_task=85)
        self.assertEqual(eng._task_detour_target(w, w.me, gm, "S01", "S15"), "TN")

    def test_no_catch_up_conservative_stays_put(self):
        # 开关开但对手未逼近 90 → 不追平；CONSERVATIVE 仍不绕路。
        eng, gm = _engine(RiskMode.CONSERVATIVE, my_task=30)
        w = _world(me_task=30, opp_task=40)
        self.assertIsNone(eng._task_detour_target(w, w.me, gm, "S01", "S15"))

    def test_no_catch_up_when_self_already_90(self):
        eng, gm = _engine(RiskMode.CONSERVATIVE, my_task=90)
        w = _world(me_task=90, opp_task=85)
        self.assertIsNone(eng._task_detour_target(w, w.me, gm, "S01", "S15"))

    def test_catch_up_active_predicate(self):
        eng, _ = _engine()
        self.assertTrue(eng._task_catch_up_active(_world(me_task=30, opp_task=85), _world(me_task=30).me))
        self.assertFalse(eng._task_catch_up_active(_world(me_task=90, opp_task=85), _world(me_task=90).me))

    def test_flag_off_disables_catch_up(self):
        config.ENABLE_TASK_RACE = False
        eng, gm = _engine(RiskMode.CONSERVATIVE, my_task=30)
        w = _world(me_task=30, opp_task=85)
        self.assertIsNone(eng._task_detour_target(w, w.me, gm, "S01", "S15"))


class TestDeny(unittest.TestCase):
    def setUp(self):
        self._saved = config.ENABLE_TASK_DENY
        config.ENABLE_TASK_DENY = True

    def tearDown(self):
        config.ENABLE_TASK_DENY = self._saved

    def test_deny_grabs_contested_milestone_task(self):
        # 对手 85、任务 +30 跨 90 里程碑；对手 ETA=20，我方到 TN=14≤20 → 抢占。
        eng, gm = _engine(my_task=90, eta_nodes={"TN": 20})
        w = _world(opp_task=85)
        self.assertEqual(eng._task_deny_target(w, w.me, gm, "S01", "S15"), "TN")

    def test_no_deny_when_opponent_cannot_reach(self):
        eng, gm = _engine(my_task=90, eta_nodes={})   # ETA 无 TN
        w = _world(opp_task=85)
        self.assertIsNone(eng._task_deny_target(w, w.me, gm, "S01", "S15"))

    def test_no_deny_when_no_milestone_crossed(self):
        # 对手已过所有里程碑(115)，+30=145 不再跨任何里程碑 → 抢占对其无里程碑价值，不 deny。
        eng, gm = _engine(my_task=90, eta_nodes={"TN": 20})
        w = _world(opp_task=115)
        self.assertIsNone(eng._task_deny_target(w, w.me, gm, "S01", "S15"))

    def test_no_deny_when_cannot_beat_opponent(self):
        # 对手 ETA=10 < 我方到 TN(14) → 抢不过，不跑空趟。
        eng, gm = _engine(my_task=90, eta_nodes={"TN": 10})
        w = _world(opp_task=85)
        self.assertIsNone(eng._task_deny_target(w, w.me, gm, "S01", "S15"))

    def test_no_deny_when_task_protected_by_opponent(self):
        eng, gm = _engine(my_task=90, eta_nodes={"TN": 20})
        w = _world(opp_task=85, task_prot=OPP)
        self.assertIsNone(eng._task_deny_target(w, w.me, gm, "S01", "S15"))

    def test_flag_off_disables_deny(self):
        config.ENABLE_TASK_DENY = False
        eng, gm = _engine(my_task=90, eta_nodes={"TN": 20})
        w = _world(opp_task=85)
        self.assertIsNone(eng._task_deny_target(w, w.me, gm, "S01", "S15"))

    def test_crosses_milestone(self):
        eng, _ = _engine()
        self.assertTrue(eng._crosses_milestone(85, 30))    # 跨 90
        self.assertTrue(eng._crosses_milestone(50, 15))    # 跨 60
        self.assertFalse(eng._crosses_milestone(95, 10))   # 105 不跨(110 未到)
        self.assertFalse(eng._crosses_milestone(10, 20))   # 30 不跨任何里程碑


class TestTaskRaceDefaultOff(unittest.TestCase):
    def test_defaults_are_off(self):
        self.assertFalse(config.ENABLE_TASK_RACE)
        self.assertFalse(config.ENABLE_TASK_DENY)

    def test_deny_none_by_default(self):
        eng, gm = _engine(my_task=90, eta_nodes={"TN": 20})
        w = _world(opp_task=85)
        self.assertIsNone(eng._task_deny_target(w, w.me, gm, "S01", "S15"))


if __name__ == "__main__":
    unittest.main()
