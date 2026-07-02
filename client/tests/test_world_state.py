"""WorldState 解析单测。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_state import WorldState  # noqa: E402


SAMPLE_INQUIRE = {
    "matchId": "m1",
    "round": 124,
    "phase": "NORMAL",
    "players": [
        {"playerId": 1001, "teamId": "RED", "state": "IDLE", "currentNodeId": "S07",
         "freshness": 92.5, "goodFruit": 78, "badFruit": 3, "squadAvailable": 6,
         "guardActionPoint": 3, "verified": False, "delivered": False,
         "resources": {"ICE_BOX": 1, "SHORT_HORSE": 1}, "taskScore": 30},
        {"playerId": 2222, "teamId": "BLUE", "state": "MOVING", "currentNodeId": "S03"},
    ],
    "nodes": [
        {"nodeId": "S07", "resourceStock": {"ICE_BOX": 1, "FAST_HORSE": 0},
         "hasObstacle": False, "canWindow": True,
         "scouted": [{"teamId": "RED", "remainRound": 30}]},
        {"nodeId": "S10", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True},
         "hasObstacle": True, "obstacleType": "ROCKFALL"},
    ],
    "tasks": [
        {"taskId": "T_1", "taskTemplateId": "T01", "nodeId": "S03", "active": True,
         "completed": False, "failed": False, "score": 30},
        {"taskId": "T_2", "taskTemplateId": "T02", "nodeId": "S10", "active": True,
         "completed": True, "failed": False, "score": 30},
    ],
    "contests": [
        {"contestId": "C1", "contestType": "RESOURCE", "redPlayerId": 1001,
         "bluePlayerId": 2222, "resolved": False},
        {"contestId": "C2", "status": "SUPPRESSED", "redPlayerId": 1001},
    ],
    "weather": {"active": [{"type": "HEAVY_RAIN", "region": "WATER", "remainRound": 20}]},
}


class TestWorldState(unittest.TestCase):
    def setUp(self):
        self.ws = WorldState(SAMPLE_INQUIRE, player_id=1001)

    def test_basic(self):
        self.assertEqual(self.ws.round, 124)
        self.assertEqual(self.ws.phase, "NORMAL")
        self.assertFalse(self.ws.is_rush)

    def test_me_and_opponent(self):
        self.assertIsNotNone(self.ws.me)
        self.assertEqual(self.ws.me.team_id, "RED")
        self.assertEqual(self.ws.me.current_node_id, "S07")
        self.assertEqual(self.ws.me.good_fruit, 78)
        self.assertEqual(self.ws.me.resource_count("ICE_BOX"), 1)
        self.assertTrue(self.ws.me.is_idle)
        self.assertEqual(self.ws.opponent.player_id, 2222)
        self.assertEqual(self.ws.opponent.state, "MOVING")

    def test_node_states(self):
        s07 = self.ws.node("S07")
        self.assertTrue(s07.resource_available("ICE_BOX"))
        self.assertFalse(s07.resource_available("FAST_HORSE"))
        self.assertEqual(len(s07.my_scout_marks("RED")), 1)
        s10 = self.ws.node("S10")
        self.assertEqual(s10.active_guard_owner(), "BLUE")
        self.assertTrue(s10.has_obstacle)

    def test_active_tasks_excludes_completed(self):
        active = self.ws.active_tasks()
        self.assertEqual([t["taskId"] for t in active], ["T_1"])

    def test_my_contests_excludes_suppressed(self):
        mine = self.ws.my_contests()
        self.assertEqual([c["contestId"] for c in mine], ["C1"])

    def test_active_weather(self):
        self.assertEqual(self.ws.active_weather_type(), "HEAVY_RAIN")


if __name__ == "__main__":
    unittest.main()
