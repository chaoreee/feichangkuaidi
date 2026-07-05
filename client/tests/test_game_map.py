"""GameMap 单测：优先加载 samples/map_config.json（真实地图），并覆盖 start 内联结构。"""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rules  # noqa: E402
from core.game_map import GameMap  # noqa: E402

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MAP_CONFIG = os.path.join(_PROJECT_ROOT, "samples", "map_config.json")


@unittest.skipUnless(os.path.exists(_MAP_CONFIG), "samples/map_config.json 不存在")
class TestGameMapFromConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(_MAP_CONFIG, encoding="utf-8") as fh:
            cls.data = json.load(fh)
        cls.gm = GameMap(cls.data)

    def test_nodes_and_edges_count(self):
        self.assertEqual(len(self.gm.nodes), 15)
        self.assertEqual(len(self.gm.edges), 21)

    def test_roles_inferred_from_types(self):
        self.assertEqual(self.gm.start_node, "S01")
        self.assertEqual(self.gm.gate_node, "S14")
        self.assertIn("S15", self.gm.terminal_nodes)

    def test_neighbors_of_start(self):
        self.assertEqual(set(self.gm.neighbors("S01")), {"S02", "S06"})

    def test_bidirectional_reverse_edge(self):
        # 默认双向：S02->S01 也应可达
        self.assertIn("S01", self.gm.neighbors("S02"))

    def test_move_amount_matches_rules(self):
        # S01->S02 ROAD distance 30
        self.assertEqual(self.gm.move_amount("S01", "S02"),
                         rules.to_station_move_amount(30, "ROAD"))
        self.assertEqual(self.gm.move_amount("S01", "S07"), math.inf)  # 非相邻

    def test_shortest_path_start_to_terminal(self):
        path, cost = self.gm.shortest_path("S01", "S15", metric="move")
        self.assertIsNotNone(path)
        self.assertEqual(path[0], "S01")
        self.assertEqual(path[-1], "S15")
        self.assertGreater(cost, 0)
        # 路径相邻性
        for a, b in zip(path, path[1:]):
            self.assertIsNotNone(self.gm.edge_between(a, b))

    def test_route_distance_positive(self):
        self.assertGreater(self.gm.route_distance("S01", "S15"), 0)
        self.assertEqual(self.gm.distance_to_gate("S14"), 0)


class TestGameMapFromStartInline(unittest.TestCase):
    """覆盖 start 顶层 nodes/edges + gameplay.roles + 单向边。"""

    def setUp(self):
        self.data = {
            "nodes": [
                {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
                {"nodeId": "S02", "type": "STATION", "x": 1, "y": 0},
                {"nodeId": "S03", "type": "FINISH", "x": 2, "y": 0, "terminal": True},
            ],
            "edges": [
                {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S02",
                 "routeType": "ROAD", "distance": 10, "bidirectional": True},
                {"edgeId": "E2", "fromNodeId": "S02", "toNodeId": "S03",
                 "routeType": "ROAD", "distance": 10, "bidirectional": False},
            ],
            "map": {"gameplay": {"roles": {"startNodeId": "S01",
                                           "terminalNodeIds": ["S03"], "gateNodeId": "S02"}}},
        }
        self.gm = GameMap(self.data)

    def test_roles_from_gameplay(self):
        self.assertEqual(self.gm.start_node, "S01")
        self.assertEqual(self.gm.gate_node, "S02")
        self.assertEqual(self.gm.terminal_nodes, ["S03"])

    def test_oneway_edge_not_reversible(self):
        # S02->S03 单向：S03 不能回到 S02
        self.assertIn("S03", self.gm.neighbors("S02"))
        self.assertNotIn("S02", self.gm.neighbors("S03"))

    def test_path(self):
        path, cost = self.gm.shortest_path("S01", "S03")
        self.assertEqual(path, ["S01", "S02", "S03"])
        self.assertEqual(cost, 2 * rules.to_station_move_amount(10, "ROAD"))


if __name__ == "__main__":
    unittest.main()
