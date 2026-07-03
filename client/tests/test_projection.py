"""投影总线 Projector 单测（Layer 1，§4）。

覆盖：本方投影分/交付帧计算、对手信息缺失→低置信→gap=0/EVEN、
未验核加验核帧、置信度随回合上升、bus 只读不产生动作、异常安全。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from strategy.projection import Projector, RiskMode  # noqa: E402

PID = 1001
OPP = 2002

# 线性地图：S01(起点) - S02(处理点) - S14(宫门) - S15(终点)
START_DATA = {
    "matchId": "t", "durationRound": 600,
    "nodes": [
        {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "S02", "type": "STATION", "x": 1, "y": 0},
        {"nodeId": "S14", "type": "GATE", "x": 2, "y": 0},
        {"nodeId": "S15", "type": "FINISH", "x": 3, "y": 0, "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 10, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "ROAD", "distance": 10, "bidirectional": True},
        {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14",
                                   "terminalNodeIds": ["S15"], "safeZoneNodeIds": ["S15"]}}},
    "processNodes": [{"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
                     {"nodeId": "S14", "processType": "VERIFY", "processRound": 6}],
}


def make_world(round=100, me_node="S02", me_fresh=100.0, me_good=100, me_task=60,
               me_verified=False, opp=None):
    players = [{
        "playerId": PID, "teamId": "RED", "state": "IDLE", "currentNodeId": me_node,
        "verified": me_verified, "goodFruit": me_good, "freshness": me_fresh, "taskScore": me_task,
    }]
    if opp is not None:
        players.append(opp)
    return WorldState({"round": round, "phase": "NORMAL", "players": players}, PID)


def opp_player(node="S02", fresh=100.0, good=100, task=60, verified=False):
    return {"playerId": OPP, "teamId": "BLUE", "state": "IDLE", "currentNodeId": node,
            "verified": verified, "goodFruit": good, "freshness": fresh, "taskScore": task}


class TestProjector(unittest.TestCase):
    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.proj = Projector(self.ctx)

    def test_my_projection_has_score_and_deliver_frame(self):
        bus, _, _ = self.proj.build(make_world())
        self.assertIsNotNone(bus.my_projection)
        self.assertGreater(bus.my_projection.projected_score, 0)
        # 交付帧 = round + 路程 + 验核帧，必然晚于当前回合。
        self.assertGreater(bus.my_projection.deliver_frame, 100)

    def test_verify_adds_frames(self):
        unverified, _, _ = self.proj.build(make_world(me_verified=False))
        verified, _, _ = Projector(self.ctx).build(make_world(me_verified=True))
        self.assertGreater(unverified.my_projection.deliver_frame,
                           verified.my_projection.deliver_frame)

    def test_missing_opponent_is_even_zero_gap(self):
        bus, _, _ = self.proj.build(make_world(opp=None))
        self.assertIsNone(bus.opponent_projection)
        self.assertEqual(bus.gap, 0.0)
        self.assertEqual(bus.mode, RiskMode.EVEN)

    def test_opponent_projection_present_and_gap_computed(self):
        # 对手鲜度/好果更差 → 我方投影分应更高，gap>0。
        bus, _, _ = self.proj.build(make_world(me_fresh=100.0, me_good=100,
                                               opp=opp_player(fresh=60.0, good=50, task=10)))
        self.assertIsNotNone(bus.opponent_projection)
        self.assertGreater(bus.gap, 0)

    def test_confidence_rises_toward_endgame(self):
        early, _, _ = self.proj.build(make_world(round=20, opp=opp_player()))
        late, _, _ = Projector(self.ctx).build(make_world(round=500, opp=opp_player()))
        self.assertLess(early.opponent_projection.confidence,
                        late.opponent_projection.confidence)

    def test_early_game_low_confidence_stays_even(self):
        # 前段置信低于阈值：即便 gap 很大也不切档（设计预期）。
        m = Projector(self.ctx)
        for _ in range(10):
            bus, _, _ = m.build(make_world(round=20, me_fresh=100.0,
                                           opp=opp_player(fresh=30.0, good=10, task=0)))
        self.assertEqual(bus.mode, RiskMode.EVEN)

    def test_build_never_raises_on_empty_world(self):
        empty = WorldState({"round": 1, "phase": "NORMAL", "players": []}, PID)
        bus, changed, _ = self.proj.build(empty)  # me 缺失
        self.assertIsNotNone(bus)
        self.assertEqual(bus.mode, RiskMode.EVEN)


class TestProjectionIsObservationOnly(unittest.TestCase):
    """P1 铁律：接入投影总线后，动作输出与现状逐帧一致。"""

    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map

    def test_engine_populates_bus_without_changing_action(self):
        engine = DecisionEngine(self.ctx)
        world = make_world(me_node="S01", opp=opp_player(fresh=30.0, good=10, task=0))
        world.game_map = self.gm
        acts = engine.decide(world)
        # 动作仍是基线推进（S01→S02），投影总线已被填充但不影响动作。
        self.assertEqual(acts, [{"action": "MOVE", "targetNodeId": "S02"}])
        self.assertIsNotNone(engine.projection_bus)


if __name__ == "__main__":
    unittest.main()
