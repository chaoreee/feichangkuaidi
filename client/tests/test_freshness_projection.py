"""鲜度投影升级单测（Iter 25，路线感知）。

替换 AVG_FRESHNESS_LOSS_PER_FRAME=0.06 平摊为逐边路线类型累计：
FRESHNESS_LOSS_MOVE[route_type] × frames_on_edge + 处理站/验核停靠 FRESHNESS_LOSS_BASE × 帧，
乘天气鲜度系数。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rules  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.projection import (Projector, freshness_loss_for_path,  # noqa: E402
                                 AVG_FRESHNESS_LOSS_PER_FRAME)
from strategy.decision import GameContext  # noqa: E402

PID = 1001

# 混合路线地图：S01 -S02(ROAD)- S14(MOUNTAIN)- S15
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
        {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S14", "routeType": "MOUNTAIN", "distance": 10, "bidirectional": True},
        {"edgeId": "E3", "fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 10, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14",
                                   "terminalNodeIds": ["S15"], "safeZoneNodeIds": ["S15"]}}},
    "processNodes": [{"nodeId": "S02", "processType": "TRANSFER", "processRound": 4},
                     {"nodeId": "S14", "processType": "VERIFY", "processRound": 6}],
}


def edge_loss(gm, a, b):
    e = gm.edge_between(a, b)
    return rules.frames_on_edge(e.distance, e.route_type) * rules.FRESHNESS_LOSS_MOVE[e.route_type]


class TestFreshnessLossForPath(unittest.TestCase):
    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map

    def test_route_aware_loss_matches_per_edge_sum(self):
        """S01→S15 路径损耗 = ROAD 边 + MOUNTAIN 边 + S02 处理停靠(4×BASE) + 验核(6×BASE)。"""
        path = ["S01", "S02", "S14", "S15"]
        verify = 6  # 未验核
        expected = (edge_loss(self.gm, "S01", "S02")
                    + edge_loss(self.gm, "S02", "S14")
                    + edge_loss(self.gm, "S14", "S15")
                    + 4 * rules.FRESHNESS_LOSS_BASE   # S02 处理站停靠
                    + verify * rules.FRESHNESS_LOSS_BASE)  # 宫门验核停靠
        got = freshness_loss_for_path(self.gm, path, weather_coef=1.0, verify_frames=verify)
        self.assertAlmostEqual(got, expected, places=6)

    def test_gate_excluded_from_process_stop_loop(self):
        """gate(S14) 在 process_nodes 但其停靠由 verify_frames 单独计，不重复。"""
        path = ["S02", "S14", "S15"]
        # verify_frames=0 → 不计验核；S14 虽在 process_nodes 但 =gate → 跳过
        got = freshness_loss_for_path(self.gm, path, weather_coef=1.0, verify_frames=0)
        expected = (edge_loss(self.gm, "S02", "S14") + edge_loss(self.gm, "S14", "S15"))
        self.assertAlmostEqual(got, expected, places=6)

    def test_weather_coef_multiplies(self):
        """天气鲜度系数(HOT=1.5)整体放大移动+停靠损耗。"""
        path = ["S01", "S02"]
        base = freshness_loss_for_path(self.gm, path, weather_coef=1.0)
        hot = freshness_loss_for_path(self.gm, path, weather_coef=rules.FRESHNESS_WEATHER_COEF["HOT"])
        self.assertAlmostEqual(hot, base * 1.5, places=6)

    def test_mountain_higher_loss_than_flat_0_06(self):
        """MOUNTAIN 边损耗率 0.07 > 平摊 0.06 → 路线感知比旧模型更准（不等于 frames×0.06）。"""
        path = ["S02", "S14"]  # MOUNTAIN 边
        # S14 是 gate（途经终点），不算处理站
        got = freshness_loss_for_path(self.gm, path, weather_coef=1.0, verify_frames=0)
        frames = rules.frames_on_edge(10, "MOUNTAIN")
        self.assertNotAlmostEqual(got, frames * AVG_FRESHNESS_LOSS_PER_FRAME, places=3)
        self.assertAlmostEqual(got, frames * rules.FRESHNESS_LOSS_MOVE["MOUNTAIN"], places=6)

    def test_empty_path_safe(self):
        self.assertEqual(freshness_loss_for_path(self.gm, [], 1.0, 0), 0.0)
        self.assertEqual(freshness_loss_for_path(self.gm, ["S01"], 1.0, 0), 0.0)


class TestProjectorUsesRouteAwareFreshness(unittest.TestCase):
    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.proj = Projector(self.ctx)

    def _world(self, node, fresh, verified):
        inq = {"round": 100, "phase": "NORMAL",
               "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE",
                            "currentNodeId": node, "verified": verified,
                            "goodFruit": 100, "freshness": fresh, "taskScore": 90}]}
        return WorldState(inq, PID)

    def test_proj_fresh_equals_freshness_minus_route_loss(self):
        """_project_player 的 proj_fresh = freshness − freshness_loss_for_path（路线感知）。"""
        w = self._world("S02", fresh=100.0, verified=False)
        gm = self.ctx.game_map
        path, _ = gm.time_optimal_path("S02", "S15")
        expected_loss = freshness_loss_for_path(gm, path, 1.0, verify_frames=6)
        my = self.proj._project_player(w, w.me, gm, "S15", 100, is_me=True)
        self.assertAlmostEqual(my.projected_freshness, max(0.0, 100.0 - expected_loss), places=4)

    def test_proj_fresh_not_flat_0_06(self):
        """proj_fresh 不等于旧 frames×0.06 平摊（路线感知生效）。"""
        w = self._world("S02", fresh=100.0, verified=False)
        gm = self.ctx.game_map
        _, travel = gm.time_optimal_path("S02", "S15")
        my = self.proj._project_player(w, w.me, gm, "S15", 100, is_me=True)
        flat = max(0.0, 100.0 - (travel + 6) * AVG_FRESHNESS_LOSS_PER_FRAME)
        self.assertNotAlmostEqual(my.projected_freshness, flat, places=2)


if __name__ == "__main__":
    unittest.main()
