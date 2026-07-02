"""pathfind Dijkstra 单测。"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import pathfind  # noqa: E402


class TestPathfind(unittest.TestCase):
    def setUp(self):
        # A-B(1)-C(1) 与 A-C(5) 直连；最短 A->C 应走 A-B-C=2
        self.adj = {
            "A": [("B", 1), ("C", 5)],
            "B": [("C", 1)],
            "C": [],
        }

    def test_shortest_picks_cheaper_multi_hop(self):
        path, cost = pathfind.shortest_path(self.adj, "A", "C")
        self.assertEqual(path, ["A", "B", "C"])
        self.assertEqual(cost, 2)

    def test_source_equals_target(self):
        path, cost = pathfind.shortest_path(self.adj, "A", "A")
        self.assertEqual(path, ["A"])
        self.assertEqual(cost, 0)

    def test_unreachable(self):
        adj = {"A": [("B", 1)], "B": [], "Z": []}
        path, cost = pathfind.shortest_path(adj, "A", "Z")
        self.assertIsNone(path)
        self.assertEqual(cost, math.inf)


if __name__ == "__main__":
    unittest.main()
