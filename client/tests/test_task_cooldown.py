"""CLAIM_TASK 重试风暴修复单测（Iter 25）。

真实 trace：客户端在 S10 对已被 OBJECT_BUSY 拒绝的任务反复重发同 taskId（r270-296 连停 30+ 帧）。
修复：_apply_rejection_feedback 对 CLAIM_TASK+OBJECT_BUSY 设 task 级冷却；_maybe_task 跳过冷却中
的 taskId；冷却过期恢复。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from protocol.enums import Action  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402

PID = 1001

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
    "processNodes": [{"nodeId": "S02", "processType": "TRANSFER", "processRound": 4}],
}

TASK_TK1 = {"taskId": "TK1", "taskTemplateId": "T01", "nodeId": "S02",
            "score": 30, "processRound": 3, "active": True}


def world_with_task(round_, node="S02", task_score=60, action_results=None):
    inq = {
        "round": round_, "phase": "NORMAL",
        "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE",
                     "currentNodeId": node, "verified": False,
                     "goodFruit": 100, "freshness": 100.0, "taskScore": task_score}],
        "tasks": [dict(TASK_TK1)],
        "actionResults": action_results or [],
    }
    return WorldState(inq, PID)


class TestTaskCooldown(unittest.TestCase):
    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.engine = DecisionEngine(self.ctx)

    def test_rejection_sets_task_cooldown(self):
        """CLAIM_TASK 被 OBJECT_BUSY 拒 → _task_cooldown[taskId] = round + REJECT_TASK_COOLDOWN_ROUNDS。"""
        rnd = 200
        self.engine._last_main_action = {"action": Action.CLAIM_TASK, "taskId": "TK1"}
        # action_results 标记上一帧 (rnd-1) 本玩家被拒 OBJECT_BUSY
        ar = [{"playerId": PID, "round": rnd - 1, "accepted": False, "errorCode": "OBJECT_BUSY"}]
        w = world_with_task(rnd, action_results=ar)
        self.engine._apply_rejection_feedback(w)
        self.assertEqual(self.engine._task_cooldown.get("TK1"),
                         rnd + config.REJECT_TASK_COOLDOWN_ROUNDS)

    def test_maybe_task_skips_cooldowned_task(self):
        """冷却中的 taskId 被 _maybe_task 跳过（不再重发）；过期后恢复领取。"""
        rnd = 200
        w = world_with_task(rnd)
        gm = self.ctx.game_map
        # 未冷却 → 领取 TK1
        act = self.engine._maybe_task(w, w.me, gm, "S02", "S15")
        self.assertIsNotNone(act)
        self.assertEqual(act.get("taskId"), "TK1")
        # 设冷却（截止 = rnd + cooldown）→ 跳过
        self.engine._task_cooldown["TK1"] = rnd + config.REJECT_TASK_COOLDOWN_ROUNDS
        act2 = self.engine._maybe_task(w, w.me, gm, "S02", "S15")
        self.assertIsNone(act2)
        # 过期后恢复
        w_late = world_with_task(rnd + config.REJECT_TASK_COOLDOWN_ROUNDS + 1)
        act3 = self.engine._maybe_task(w_late, w_late.me, gm, "S02", "S15")
        self.assertIsNotNone(act3)
        self.assertEqual(act3.get("taskId"), "TK1")

    def test_non_object_busy_does_not_cooldown(self):
        """非 OBJECT_BUSY 拒绝码（如 TASK_NOT_AVAILABLE）不触发 task 冷却。"""
        rnd = 200
        self.engine._last_main_action = {"action": Action.CLAIM_TASK, "taskId": "TK1"}
        ar = [{"playerId": PID, "round": rnd - 1, "accepted": False,
               "errorCode": "TASK_NOT_AVAILABLE"}]
        w = world_with_task(rnd, action_results=ar)
        self.engine._apply_rejection_feedback(w)
        self.assertNotIn("TK1", self.engine._task_cooldown)

    def test_move_rejection_still_blocks_node(self):
        """回归：MOVE 拉黑节点逻辑不受影响。"""
        rnd = 200
        self.engine._last_main_action = {"action": Action.MOVE, "targetNodeId": "S14"}
        ar = [{"playerId": PID, "round": rnd - 1, "accepted": False,
               "errorCode": "MOVE_BLOCKED_BY_GUARD"}]
        w = world_with_task(rnd, action_results=ar)
        self.engine._apply_rejection_feedback(w)
        self.assertEqual(self.engine._cooldown.get("S14"), rnd + config.REJECT_BLOCK_ROUNDS)


if __name__ == "__main__":
    unittest.main()
