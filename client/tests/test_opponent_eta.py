"""P3 §6.1 对手轨迹 ETA 单测（纯观测基础设施）。

覆盖：在节点/在途(move_progress)的 ETA、未验核加验核帧、任务/资源节点 ETA、
无对手降级、置信随回合上升、轨迹变化降低置信、接入 decide 不改动作。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from strategy.projection import Projector  # noqa: E402

PID = 1001
OPP = 2002


def _node(nid, typ="STATION", start=False, terminal=False):
    return {"nodeId": nid, "type": typ, "x": 0, "y": 0, "start": start, "terminal": terminal}


def _edge(a, b, dist=10):
    return {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": dist, "bidirectional": True}


# S01 - S02(任务点/资源点) - S14(gate) - S15(term)
SD = {"matchId": "e", "durationRound": 600,
      "nodes": [_node("S01", "START", start=True), _node("S02"),
                _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
      "edges": [_edge("S01", "S02"), _edge("S02", "S14"), _edge("S14", "S15")],
      "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14",
                                     "terminalNodeIds": ["S15"]}}},
      "processNodes": [{"nodeId": "S14", "processType": "VERIFY", "processRound": 6}]}


def _world(opp_node="S01", opp_next=None, progress=0.0, verified=False, rnd=100,
           tasks=None, nodes=None):
    opp = {"playerId": OPP, "teamId": "BLUE", "state": "MOVING" if opp_next else "IDLE",
           "currentNodeId": opp_node, "nextNodeId": opp_next, "moveProgress": progress,
           "verified": verified, "goodFruit": 100, "freshness": 100.0}
    me = {"playerId": PID, "teamId": "RED", "state": "IDLE", "currentNodeId": "S01",
          "verified": False, "goodFruit": 100, "freshness": 100.0}
    inquire = {"round": rnd, "phase": "NORMAL", "players": [me, opp],
               "tasks": tasks or [], "nodes": nodes or []}
    return WorldState(inquire, PID, None)


def _eta(world, projector=None):
    ctx = GameContext(PID, "RED", 0, SD)
    p = projector or Projector(ctx)
    return p.build_opponent_eta(world)


class TestOpponentEta(unittest.TestCase):
    def setUp(self):
        self.gm = GameMap(SD)
        # 各边 ROAD dist10 = 14 帧；S01→S14=28，S01→S15=42。
        self.edge_frames = 14

    def test_eta_from_node(self):
        eta = _eta(_world(opp_node="S01"))
        self.assertEqual(eta.from_node, "S01")
        self.assertEqual(eta.to_gate, 2 * self.edge_frames)          # S01→S02→S14
        # to_finish = S01→S15 (42) + 验核 6（未验核）
        self.assertEqual(eta.to_finish, 3 * self.edge_frames + 6)

    def test_eta_on_edge_adds_remaining(self):
        # 在 S01→S02 边上、已走一半：以 S02 起算 + 到 S02 残余帧(ceil(14*0.5)=7)。
        eta = _eta(_world(opp_node="S01", opp_next="S02", progress=0.5))
        self.assertEqual(eta.from_node, "S02")
        self.assertEqual(eta.to_gate, 7 + self.edge_frames)          # 残余7 + S02→S14(14)

    def test_verified_opponent_no_verify_frames(self):
        eta = _eta(_world(opp_node="S01", verified=True))
        self.assertEqual(eta.to_finish, 3 * self.edge_frames)        # 无验核加成

    def test_to_nodes_includes_task_and_resource(self):
        tasks = [{"taskId": "T", "nodeId": "S02", "active": True, "completed": False}]
        nodes = [{"nodeId": "S14", "resourceStock": {"ICE_BOX": 1}}]
        eta = _eta(_world(opp_node="S01", tasks=tasks, nodes=nodes))
        self.assertEqual(eta.eta("S02"), self.edge_frames)           # S01→S02
        self.assertEqual(eta.eta("S14"), 2 * self.edge_frames)       # S01→S14

    def test_no_opponent_degrades(self):
        me = {"playerId": PID, "teamId": "RED", "state": "IDLE", "currentNodeId": "S01"}
        w = WorldState({"round": 100, "phase": "NORMAL", "players": [me]}, PID, None)
        eta = _eta(w)
        self.assertIsNone(eta.from_node)
        self.assertEqual(eta.confidence, 0.0)

    def test_confidence_rises_toward_endgame(self):
        early = _eta(_world(rnd=20))
        late = _eta(_world(rnd=500))
        self.assertLess(early.confidence, late.confidence)

    def test_route_change_lowers_confidence(self):
        ctx = GameContext(PID, "RED", 0, SD)
        p = Projector(ctx)
        # 对手停在 S01，先指向 S02。
        stable = p.build_opponent_eta(_world(opp_node="S01", opp_next="S02", rnd=300))
        # 原地把目标改到 S14（路线变更）。
        changed = p.build_opponent_eta(_world(opp_node="S01", opp_next="S14", rnd=301))
        self.assertLess(changed.confidence, stable.confidence)


class TestEtaIsObservationOnly(unittest.TestCase):
    def test_decide_populates_eta_without_changing_action(self):
        ctx = GameContext(PID, "RED", 0, SD)
        eng = DecisionEngine(ctx)
        w = _world(opp_node="S02")
        w.game_map = ctx.game_map
        acts = eng.decide(w)
        # 基线推进 S01→S02，不受 ETA 影响；ETA 已填充。
        self.assertEqual(acts, [{"action": "MOVE", "targetNodeId": "S02"}])
        self.assertIsNotNone(eng.opponent_eta)
        self.assertEqual(eng.opponent_eta.from_node, "S02")


if __name__ == "__main__":
    unittest.main()
