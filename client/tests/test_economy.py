"""M4 收益策略单测：任务/资源领取/鲜度/加速/护果令与时间预算守卫。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402

PID = 1001

# 线性地图：S01 - SA - S14(宫门) - S15(终点)，各段 ROAD 20（SA→S15 距离 40 > 30，属"远"）
START_DATA = {
    "matchId": "e", "durationRound": 600,
    "nodes": [
        {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "SA", "type": "STATION", "x": 1, "y": 0},
        {"nodeId": "S14", "type": "GATE", "x": 2, "y": 0},
        {"nodeId": "S15", "type": "FINISH", "x": 3, "y": 0, "terminal": True},
    ],
    "edges": [
        {"fromNodeId": "S01", "toNodeId": "SA", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"fromNodeId": "SA", "toNodeId": "S14", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 20, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
    "processNodes": [],
}


def make_world(node="SA", state="IDLE", phase="NORMAL", verified=False, delivered=False,
               freshness=100.0, resources=None, buffs=None, rush_used=0, tasks=None,
               stock=None, rnd=20, game_map=None, task_score=0):
    inquire = {
        "round": rnd, "phase": phase,
        "players": [{
            "playerId": PID, "teamId": "RED", "state": state, "currentNodeId": node,
            "verified": verified, "delivered": delivered, "goodFruit": 100, "freshness": freshness,
            "resources": resources or {}, "buffs": buffs or [], "rushTacticUsedCount": rush_used,
            "taskScore": task_score,
        }],
        "nodes": [{"nodeId": node, "resourceStock": stock or {}}],
        "tasks": tasks or [],
        "events": [],
    }
    return WorldState(inquire, PID, game_map)


class TestEconomy(unittest.TestCase):
    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map

    def act(self, **kw):
        kw.setdefault("game_map", self.gm)
        eng = DecisionEngine(self.ctx)
        acts = eng.decide(make_world(**kw))
        return acts[0] if acts else None

    # 鲜度
    def test_ice_box_rescue_when_low(self):
        a = self.act(freshness=70.0, resources={"ICE_BOX": 1})
        self.assertEqual(a, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})

    def test_no_ice_box_when_fresh(self):
        a = self.act(freshness=95.0, resources={"ICE_BOX": 1})
        self.assertNotEqual(a, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})

    def test_ice_box_fires_just_above_80_threshold(self):
        # Iter 34：阈值 78→81，在跌破 80 好果转坏阈值前用冰鉴救回 1 篓好果
        a = self.act(freshness=80.5, resources={"ICE_BOX": 1})
        self.assertEqual(a, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})

    def test_no_ice_box_at_82(self):
        # 82 仍高于阈值 81，不使用冰鉴（保留给真正跌破时）
        a = self.act(freshness=82.0, resources={"ICE_BOX": 1})
        self.assertNotEqual(a, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})

    # 任务
    def test_claim_task_at_node(self):
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA", "score": 30,
                  "processRound": 3, "active": True, "completed": False}]
        a = self.act(tasks=tasks)
        self.assertEqual(a, {"action": "CLAIM_TASK", "taskId": "TK"})

    def test_skip_task_when_score_capped(self):
        # 任务分已达 180 上限（base=130+里程碑50）→ 顺路任务边际收益 0 → 不停车烧用时分/鲜度
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA", "score": 30,
                  "processRound": 3, "active": True, "completed": False}]
        a = self.act(tasks=tasks, task_score=130)
        self.assertNotEqual(a.get("action") if a else None, "CLAIM_TASK")

    def test_claim_task_when_marginal_gain(self):
        # base=50 未跨里程碑，加 30 分跨过 60 里程碑 → 有正边际收益 → 领取
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA", "score": 30,
                  "processRound": 3, "active": True, "completed": False}]
        a = self.act(tasks=tasks, task_score=50)
        self.assertEqual(a, {"action": "CLAIM_TASK", "taskId": "TK"})

    def test_skip_t04_t06(self):
        tasks = [{"taskId": "TK", "taskTemplateId": "T04", "nodeId": "SA", "score": 30,
                  "processRound": 6, "active": True, "completed": False}]
        a = self.act(tasks=tasks)
        self.assertNotEqual(a.get("action"), "CLAIM_TASK")

    def test_skip_opponent_protected_task(self):
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA", "score": 30, "processRound": 3,
                  "active": True, "completed": False, "protectionPlayerId": 2222}]
        a = self.act(tasks=tasks)
        self.assertNotEqual(a.get("action"), "CLAIM_TASK")

    def test_task_skipped_when_time_short(self):
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA", "score": 30,
                  "processRound": 3, "active": True, "completed": False}]
        a = self.act(tasks=tasks, rnd=590)  # 临近 600，做任务将赶不上交付
        self.assertNotEqual(a.get("action"), "CLAIM_TASK")

    # 资源领取
    def test_claim_ice_box_when_lacking(self):
        a = self.act(stock={"ICE_BOX": 1})
        self.assertEqual(a, {"action": "CLAIM_RESOURCE", "targetNodeId": "SA", "resourceType": "ICE_BOX"})

    def test_claim_horse_when_far_and_no_horse(self):
        a = self.act(stock={"FAST_HORSE": 1})
        self.assertEqual(a, {"action": "CLAIM_RESOURCE", "targetNodeId": "SA", "resourceType": "FAST_HORSE"})

    def test_no_claim_horse_when_already_have(self):
        a = self.act(stock={"FAST_HORSE": 1}, resources={"SHORT_HORSE": 1})
        self.assertNotEqual(a.get("action"), "CLAIM_RESOURCE")

    # 加速（移动中）
    def test_use_horse_when_moving_far(self):
        a = self.act(node="SA", state="MOVING", resources={"FAST_HORSE": 1})
        self.assertEqual(a, {"action": "USE_RESOURCE", "resourceType": "FAST_HORSE"})

    def test_no_horse_when_buff_active(self):
        # 已有马类增益 → 不再用马；但移动中仍主动续行（推进），不空等
        a = self.act(node="SA", state="MOVING", resources={"FAST_HORSE": 1},
                     buffs=[{"type": "FAST_HORSE", "remainingRound": 5}])
        self.assertNotEqual(a.get("action") if a else None, "USE_RESOURCE")
        self.assertEqual((a or {}).get("action"), "MOVE")

    def test_no_horse_when_near_terminal(self):
        a = self.act(node="S14", state="MOVING", resources={"FAST_HORSE": 1})  # S14→S15=20<30
        self.assertIsNone(a)

    # 护果令
    def test_rush_protect_when_rush_and_low_fresh(self):
        a = self.act(phase="RUSH", freshness=80.0)
        self.assertEqual(a, {"action": "RUSH_PROTECT"})

    def test_no_rush_protect_when_already_used(self):
        a = self.act(phase="RUSH", freshness=80.0, rush_used=1)
        self.assertNotEqual(a.get("action"), "RUSH_PROTECT")


if __name__ == "__main__":
    unittest.main()
