"""P4 §7 条件化 SET_GUARD 单测（默认关，本测显式打开开关验证行为）。

覆盖：锁胜局在关键关隘设卡（denial 达标）；六条件与 denial 各守卫（领先不足/非关隘/
已有卡/置信低/ETA 窗口外/好果不足/对手可低价破卡）；默认关与 ENABLE_OFFENSIVE 基线并存。
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

PID = 1001
OPP = 2002

# S01 - SK(关键关隘) - S14(gate) - S15(term)；me 在 SK。
SD = {"matchId": "cg", "durationRound": 600,
      "nodes": [{"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
                {"nodeId": "SK", "type": "KEY_PASS", "x": 1, "y": 0},
                {"nodeId": "S14", "type": "GATE", "x": 2, "y": 0},
                {"nodeId": "S15", "type": "FINISH", "x": 3, "y": 0, "terminal": True}],
      "edges": [{"fromNodeId": "S01", "toNodeId": "SK", "routeType": "ROAD", "distance": 10, "bidirectional": True},
                {"fromNodeId": "SK", "toNodeId": "S14", "routeType": "ROAD", "distance": 10, "bidirectional": True},
                {"fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10, "bidirectional": True}],
      "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
      "processNodes": []}


def _world(me_good=100, node="SK", opp_bad=0, opp_task=90, guard=None, rnd=100):
    me = {"playerId": PID, "teamId": "RED", "state": "IDLE", "currentNodeId": node,
          "verified": True, "goodFruit": me_good, "freshness": 100.0}
    opp = {"playerId": OPP, "teamId": "BLUE", "state": "MOVING", "currentNodeId": "S01",
           "verified": False, "goodFruit": 100, "badFruit": opp_bad, "freshness": 100.0,
           "taskScore": opp_task}
    nodes = []
    if guard:
        nodes.append({"nodeId": "SK", "guard": {"active": True, "defense": guard, "ownerTeamId": "RED"}})
    return WorldState({"round": rnd, "phase": "NORMAL", "players": [me, opp], "nodes": nodes}, PID, None)


def _bus(mode=RiskMode.CONSERVATIVE, gap=100.0):
    my = Projection(PID, 130, 600.0, 100, 100.0, 90, 0, (), 0.9)
    opp = Projection(OPP, 130, 500.0, 100, 100.0, 60, 0, (), 0.8)
    return ProjectionBus(my, opp, gap, mode, "t")


def _engine(mode=RiskMode.CONSERVATIVE, gap=100.0, conf=0.8, sk_eta=30):
    eng = DecisionEngine(GameContext(PID, "RED", 0, SD))
    eng.projection_bus = _bus(mode, gap)
    eng.opponent_eta = OpponentEta("S01", 30, 60, {"SK": sk_eta} if sk_eta is not None else {}, False, conf)
    return eng, GameMap(SD)


class TestConditionalGuard(unittest.TestCase):
    def setUp(self):
        self._saved = config.ENABLE_CONDITIONAL_GUARD
        config.ENABLE_CONDITIONAL_GUARD = True

    def tearDown(self):
        config.ENABLE_CONDITIONAL_GUARD = self._saved

    def _guard(self, eng, gm, w):
        return eng._conditional_guard(w, w.me, gm, "SK", "S15")

    def test_sets_guard_when_locking_win(self):
        # 锁胜(CONSERVATIVE gap100) + 关键关隘 + 对手 ETA 30∈(5,60] + 置信0.8 + 好果足
        # + 对手无坏果(defense6 破不了,只能强制通行,denial≈5.25≥4) → 设卡。
        eng, gm = _engine()
        a = self._guard(eng, gm, _world())
        self.assertEqual(a.get("action"), "SET_GUARD")
        self.assertEqual(a.get("targetNodeId"), "SK")
        self.assertEqual(a.get("extraGoodFruit"), 2)
        self.assertIsNotNone(eng.guard_decision)

    def test_no_guard_when_not_conservative(self):
        eng, gm = _engine(mode=RiskMode.EVEN)
        self.assertIsNone(self._guard(eng, gm, _world()))

    def test_no_guard_when_lead_too_small(self):
        eng, gm = _engine(gap=config.GUARD_MIN_LEAD - 1)
        self.assertIsNone(self._guard(eng, gm, _world()))

    def test_no_guard_when_low_confidence(self):
        eng, gm = _engine(conf=config.GUARD_MIN_CONFIDENCE - 0.01)
        self.assertIsNone(self._guard(eng, gm, _world()))

    def test_no_guard_when_opp_eta_out_of_window(self):
        eng, gm = _engine(sk_eta=config.GUARD_SURVIVAL_WINDOW + 5)
        self.assertIsNone(self._guard(eng, gm, _world()))

    def test_no_guard_when_opp_eta_too_soon(self):
        # 对手在设卡生效前就通过 → 无意义。
        eng, gm = _engine(sk_eta=config.GUARD_SETUP_FRAMES)
        self.assertIsNone(self._guard(eng, gm, _world()))

    def test_no_guard_when_opp_not_on_route(self):
        eng, gm = _engine(sk_eta=None)  # ETA 无 SK
        self.assertIsNone(self._guard(eng, gm, _world()))

    def test_no_guard_when_good_fruit_insufficient(self):
        # 好果 21：投入 base1+extra 后守不住下限 20（21-1-2=18<20，-1-1=19<20，-1-0=20≥20→extra0,defense2）。
        # defense2 时对手 (1,0)=2 可破且损1好果1.8 与强制通行取小 → denial 可能<4，验证不设卡或退化。
        eng, gm = _engine()
        a = self._guard(eng, gm, _world(me_good=21))
        # 好果紧张：要么不设卡，要么 extra 降低；此处 21 允许 extra0(留20)，但 defense2 denial 低 → 不设卡。
        self.assertIsNone(a)

    def test_no_guard_when_existing_guard(self):
        eng, gm = _engine()
        self.assertIsNone(self._guard(eng, gm, _world(guard=3)))

    def test_no_guard_when_opponent_can_break_cheaply(self):
        # 对手有 2 坏果：defense6 用 (0,2)=6 破卡、坏果不计分 → denial≈0 < 4 → 不值得设卡。
        eng, gm = _engine()
        self.assertIsNone(self._guard(eng, gm, _world(opp_bad=2)))

    def test_denial_low_when_opponent_low_task(self):
        # 对手任务分低 → 强制通行用时分损失小 → denial<4 → 不设卡。
        eng, gm = _engine()
        self.assertIsNone(self._guard(eng, gm, _world(opp_task=10)))


class TestGuardDispatchAndDefaults(unittest.TestCase):
    def test_conditional_default_off(self):
        self.assertFalse(config.ENABLE_CONDITIONAL_GUARD)

    def test_no_guard_when_both_flags_off(self):
        eng, gm = _engine()
        self.assertIsNone(eng._maybe_set_guard(_world(), _world().me, gm, "SK", "S15"))

    def test_offensive_basic_path_preserved(self):
        # ENABLE_OFFENSIVE(基线) 仍走 _basic_set_guard：关键关隘投 1 篓，不看投影。
        saved = config.ENABLE_OFFENSIVE
        config.ENABLE_OFFENSIVE = True
        try:
            eng, gm = _engine()
            a = eng._maybe_set_guard(_world(), _world().me, gm, "SK", "S15")
            self.assertEqual(a, {"action": "SET_GUARD", "targetNodeId": "SK", "extraGoodFruit": 1})
        finally:
            config.ENABLE_OFFENSIVE = saved

    def test_conditional_takes_precedence_over_offensive(self):
        # 两开关都开：走条件化（投影驱动，extra=2），非基线的 extra=1。
        so, sc = config.ENABLE_OFFENSIVE, config.ENABLE_CONDITIONAL_GUARD
        config.ENABLE_OFFENSIVE = True
        config.ENABLE_CONDITIONAL_GUARD = True
        try:
            eng, gm = _engine()
            a = eng._maybe_set_guard(_world(), _world().me, gm, "SK", "S15")
            self.assertEqual(a.get("extraGoodFruit"), 2)
        finally:
            config.ENABLE_OFFENSIVE, config.ENABLE_CONDITIONAL_GUARD = so, sc


if __name__ == "__main__":
    unittest.main()
