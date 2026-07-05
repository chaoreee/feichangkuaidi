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
    "taskTemplates": [
        {"taskTemplateId": "T01", "score": 30, "processRound": 3},
        {"taskTemplateId": "T04", "score": 30, "processRound": 6, "processType": "CLEAR_OBSTACLE"},
        {"taskTemplateId": "T06", "score": 30, "processRound": 3,
         "requiredResourceTypes": ["FAST_HORSE", "SHORT_HORSE"]},
    ],
}


def make_world(node="SA", state="IDLE", phase="NORMAL", verified=False, delivered=False,
               freshness=100.0, resources=None, buffs=None, rush_used=0, tasks=None,
               stock=None, rnd=20, game_map=None):
    inquire = {
        "round": rnd, "phase": phase,
        "players": [{
            "playerId": PID, "teamId": "RED", "state": state, "currentNodeId": node,
            "verified": verified, "delivered": delivered, "goodFruit": 100, "freshness": freshness,
            "resources": resources or {}, "buffs": buffs or [], "rushTacticUsedCount": rush_used,
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

    def test_ice_box_before_threshold(self):
        # 鲜度 84 距 80 阈值 4(≤5) → 提前用冰鉴挡阈值，而非等到跌破 78
        a = self.act(freshness=84.0, resources={"ICE_BOX": 1})
        self.assertEqual(a, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})

    def test_ice_box_anytime_below_cap(self):
        # Iter15：鲜度 89（距 80 阈值 9，旧"近阈值≤7"不用）→ 现改为≤90 即用，叠加 +10 永久偏移
        a = self.act(freshness=89.0, resources={"ICE_BOX": 1})
        self.assertEqual(a, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})

    def test_ice_box_used_repeatedly_as_freshness_decays(self):
        # Iter15：鲜度≤90 即用；用后鲜度回跳≥90 则不再用（避免撞 100 上限浪费）
        a = self.act(freshness=89.0, resources={"ICE_BOX": 2})
        self.assertEqual(a, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})
        # 鲜度已被拉回 ≥90（模拟上一帧用过后回跳）→ 不重复使用
        a2 = self.act(freshness=95.0, resources={"ICE_BOX": 1})
        self.assertNotEqual(a2, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})

    def test_no_ice_box_above_cap(self):
        # 鲜度 92：用冰鉴会撞 100 上限造成浪费，且抢破关令验核额度 → 不用
        a = self.act(freshness=92.0, resources={"ICE_BOX": 1})
        self.assertNotEqual(a.get("action") if a else None, "USE_RESOURCE")

    def test_no_ice_box_when_fresh(self):
        a = self.act(freshness=95.0, resources={"ICE_BOX": 1})
        self.assertNotEqual(a, {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"})

    # 任务
    def test_claim_task_at_node(self):
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA",
                  "processRound": 3, "active": True, "completed": False}]
        a = self.act(tasks=tasks)
        self.assertEqual(a, {"action": "CLAIM_TASK", "taskId": "TK"})

    def test_t04_claimed_not_skipped(self):
        # Iter16：不再按模板 ID 跳过 T04；按 processType 判定，在节点上即可领取（+30 分）
        tasks = [{"taskId": "TK", "taskTemplateId": "T04", "nodeId": "SA",
                  "processType": "CLEAR_OBSTACLE",
                  "processRound": 6, "active": True, "completed": False}]
        a = self.act(tasks=tasks)
        self.assertEqual(a, {"action": "CLAIM_TASK", "taskId": "TK"})

    def test_t04_claimed_from_adjacent_node(self):
        # §5.2：T04 可在障碍节点或相邻节点处理；agent 在 S01、T04 挂在 SA（相邻）→ 仍可领取
        tasks = [{"taskId": "TK", "taskTemplateId": "T04", "nodeId": "SA",
                  "processType": "CLEAR_OBSTACLE",
                  "processRound": 6, "active": True, "completed": False}]
        a = self.act(tasks=tasks, node="S01")
        self.assertEqual(a, {"action": "CLAIM_TASK", "taskId": "TK"})

    def test_t06_claimed_when_horse_available(self):
        # Iter16：T06 需消耗马，持有马时领取（+30 分 > 单匹马的移速收益）
        tasks = [{"taskId": "TK", "taskTemplateId": "T06", "nodeId": "SA",
                  "processRound": 3, "active": True, "completed": False}]
        a = self.act(tasks=tasks, resources={"FAST_HORSE": 1})
        self.assertEqual(a, {"action": "CLAIM_TASK", "taskId": "TK"})

    def test_t06_skipped_when_no_horse(self):
        # 持有马是 T06 的硬性前置；无马时不领取（避免被服务端拒绝）
        tasks = [{"taskId": "TK", "taskTemplateId": "T06", "nodeId": "SA",
                  "processRound": 3, "active": True, "completed": False}]
        a = self.act(tasks=tasks, resources={})
        self.assertNotEqual(a.get("action"), "CLAIM_TASK")

    def test_skip_opponent_protected_task(self):
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA", "processRound": 3,
                  "active": True, "completed": False, "protectionPlayerId": 2222}]
        a = self.act(tasks=tasks)
        self.assertNotEqual(a.get("action"), "CLAIM_TASK")

    def test_task_skipped_when_time_short(self):
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA",
                  "processRound": 3, "active": True, "completed": False}]
        a = self.act(tasks=tasks, rnd=590)  # 临近 600，做任务将赶不上交付
        self.assertNotEqual(a.get("action"), "CLAIM_TASK")

    # 资源领取
    def test_claim_ice_box_when_lacking(self):
        a = self.act(stock={"ICE_BOX": 1})
        self.assertEqual(a, {"action": "CLAIM_RESOURCE", "targetNodeId": "SA", "resourceType": "ICE_BOX"})

    def test_claim_ice_box_exempt_from_time_budget(self):
        # P3：临近 600 帧时其他资源/任务被 _can_afford 拒，但冰鉴领取豁免仍生效
        # （2 帧成本 < 1 篓好果转坏的 3.6 分损失；真机归因 7/7 跨 80 阈值根因是冰鉴领不到）
        a = self.act(stock={"ICE_BOX": 1}, rnd=590)
        self.assertEqual(a, {"action": "CLAIM_RESOURCE", "targetNodeId": "SA", "resourceType": "ICE_BOX"})

    def test_no_claim_horse_when_time_short(self):
        # 对照：马领取仍受 _can_afford 约束，时间紧时不领（豁免仅限冰鉴）
        a = self.act(stock={"FAST_HORSE": 1}, rnd=590)
        self.assertNotEqual((a or {}).get("action"), "CLAIM_RESOURCE")

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
