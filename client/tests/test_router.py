"""时间感知路由单测：固定处理耗时应能改变选路。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_map import GameMap  # noqa: E402

# 两条并行路：A 经 S2（距离更短，但 S2 是重处理点 100 帧）；B 经 S3（距离略长，无处理）。
MAP = {
    "nodes": [
        {"nodeId": "S1", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "S2", "type": "STATION", "x": 1, "y": 1},
        {"nodeId": "S3", "type": "STATION", "x": 1, "y": -1},
        {"nodeId": "S4", "type": "FINISH", "x": 2, "y": 0, "terminal": True},
    ],
    "edges": [
        {"fromNodeId": "S1", "toNodeId": "S2", "routeType": "ROAD", "distance": 10, "bidirectional": True},
        {"fromNodeId": "S2", "toNodeId": "S4", "routeType": "ROAD", "distance": 10, "bidirectional": True},
        {"fromNodeId": "S1", "toNodeId": "S3", "routeType": "ROAD", "distance": 12, "bidirectional": True},
        {"fromNodeId": "S3", "toNodeId": "S4", "routeType": "ROAD", "distance": 12, "bidirectional": True},
    ],
    "processNodes": [{"nodeId": "S2", "processType": "TRANSFER", "processRound": 100}],
}


class TestTimeAwareRouting(unittest.TestCase):
    def setUp(self):
        self.gm = GameMap(MAP)

    def test_move_amount_prefers_shorter_distance(self):
        # 纯移动量：经 S2（距离更短）
        path, _ = self.gm.shortest_path("S1", "S4", metric="move")
        self.assertEqual(path, ["S1", "S2", "S4"])

    def test_time_aware_avoids_heavy_process(self):
        # 计入处理耗时：绕开重处理点 S2，改走 S3
        path, cost = self.gm.time_optimal_path("S1", "S4")
        self.assertEqual(path, ["S1", "S3", "S4"])
        self.assertLess(cost, 100)  # 远小于经 S2 的 100+ 帧

    def test_time_aware_without_process_prefers_shorter(self):
        # 去掉重处理后，时间路由回到更短距离的 S2
        m = dict(MAP)
        m["processNodes"] = []
        gm = GameMap(m)
        path, _ = gm.time_optimal_path("S1", "S4")
        self.assertEqual(path, ["S1", "S2", "S4"])


if __name__ == "__main__":
    unittest.main()
