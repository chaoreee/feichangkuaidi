"""日志增厚字段构造器单测（main.py 的纯函数）。

验证：Frame 对手镜像/天气、Block 变化触发与解除、Contest 字段、Reject 解析、
Budget None/inf 跳过、Start 地图角色。所有构造器对缺失数据降级（mock 蓝方
dummy/无天气/无窗口仍可用）。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from core.world_state import WorldState  # noqa: E402


# 复用 test_world_state 的 inquire 样例结构，补齐对手镜像字段与阻塞。
def _inquire(opp=None, nodes=None, contests=None, weather=None, action_results=None):
    players = [
        {"playerId": 1001, "teamId": "RED", "state": "IDLE", "currentNodeId": "S07",
         "freshness": 92.5, "goodFruit": 78, "badFruit": 3, "verified": False,
         "delivered": False, "taskScore": 30},
    ]
    if opp is not None:
        players.append(opp)
    return {
        "matchId": "m1", "round": 5, "phase": "NORMAL", "players": players,
        "nodes": nodes or [], "tasks": [], "contests": contests or [],
        "weather": weather or {}, "actionResults": action_results or [],
        "events": [],
    }


class TestFrameFields(unittest.TestCase):
    def test_opponent_mirror_full(self):
        opp = {"playerId": 2222, "teamId": "BLUE", "state": "MOVING",
               "currentNodeId": "S03", "freshness": 88, "goodFruit": 80,
               "verified": False, "delivered": False, "taskScore": 60}
        ws = WorldState(_inquire(opp=opp), player_id=1001)
        f = main.frame_fields(5, _inquire(opp=opp), ws)
        self.assertEqual(f["opp"], "S03|MOVING|88|80|60|F|F")
        self.assertEqual(f["round"], 5)
        self.assertEqual(f["node"], "S07")
        self.assertEqual(f["fresh"], 92.5)

    def test_opponent_missing_fields_degrade(self):
        # mock 蓝方 dummy：只下发 5 个字段，PlayerView.from_dict 把其余字段默认为
        # 0/0.0/False（而非 None）。真实平台会下发实际值。- 仅对真正 None 出现。
        opp = {"playerId": 2222, "teamId": "BLUE", "state": "IDLE",
               "currentNodeId": "S01", "delivered": False}
        ws = WorldState(_inquire(opp=opp), player_id=1001)
        f = main.frame_fields(5, _inquire(opp=opp), ws)
        # 默认值：fresh=0.0→0, goodFruit=0, taskScore=0, verified=False, delivered=False
        self.assertEqual(f["opp"], "S01|IDLE|0|0|0|F|F")

    def test_weather_present(self):
        opp = {"playerId": 2222, "currentNodeId": "S01"}
        inqu = _inquire(opp=opp,
                        weather={"active": [{"type": "HOT", "region": "ALL"}]})
        ws = WorldState(inqu, player_id=1001)
        f = main.frame_fields(5, inqu, ws)
        self.assertEqual(f["weather"], "HOT")

    def test_weather_absent(self):
        # mock 无 weather 字段
        ws = WorldState(_inquire(), player_id=1001)
        f = main.frame_fields(5, _inquire(), ws)
        self.assertNotIn("weather", f)

    def test_no_opponent(self):
        ws = WorldState(_inquire(), player_id=1001)
        f = main.frame_fields(5, _inquire(), ws)
        self.assertNotIn("opp", f)  # world.opponent 为 None 时不写 opp


class TestBlockDiff(unittest.TestCase):
    def _ws_with_blocks(self, nodes):
        inqu = _inquire(nodes=nodes)
        return WorldState(inqu, player_id=1001), inqu

    def test_new_block_emitted(self):
        nodes = [{"nodeId": "S10", "hasObstacle": True, "obstacleType": "FLOOD"}]
        ws, _ = self._ws_with_blocks(nodes)
        changed, cleared, cur = main.block_diff(ws, {})
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][0], "S10")
        self.assertEqual(changed[0][1], ("FLOOD", None, 0))
        self.assertEqual(cleared, [])
        self.assertIn("S10", cur)

    def test_guard_block_signature(self):
        nodes = [{"nodeId": "S12",
                  "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}}]
        ws, _ = self._ws_with_blocks(nodes)
        changed, _, cur = main.block_diff(ws, {})
        self.assertEqual(changed[0][1], (None, "BLUE", 4))

    def test_unchanged_not_reemitted(self):
        nodes = [{"nodeId": "S10", "hasObstacle": True, "obstacleType": "FLOOD"}]
        ws, _ = self._ws_with_blocks(nodes)
        _, _, cur = main.block_diff(ws, {})
        # 第二帧同样的阻塞 → 不应再次报 changed
        changed2, cleared2, _ = main.block_diff(ws, cur)
        self.assertEqual(changed2, [])
        self.assertEqual(cleared2, [])

    def test_defense_change_reemitted(self):
        nodes1 = [{"nodeId": "S12",
                   "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}}]
        ws1, _ = self._ws_with_blocks(nodes1)
        _, _, cur = main.block_diff(ws1, {})
        nodes2 = [{"nodeId": "S12",
                   "guard": {"ownerTeamId": "BLUE", "defense": 6, "active": True}}]
        ws2, _ = self._ws_with_blocks(nodes2)
        changed, _, _ = main.block_diff(ws2, cur)
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][1], (None, "BLUE", 6))

    def test_cleared_emitted(self):
        nodes1 = [{"nodeId": "S10", "hasObstacle": True, "obstacleType": "FLOOD"}]
        ws1, _ = self._ws_with_blocks(nodes1)
        _, _, cur = main.block_diff(ws1, {})
        # 下一帧障碍消失
        ws2, _ = self._ws_with_blocks([])
        changed, cleared, cur2 = main.block_diff(ws2, cur)
        self.assertEqual(changed, [])
        self.assertEqual(cleared, ["S10"])
        self.assertEqual(cur2, {})

    def test_inactive_guard_not_block(self):
        # defense=0 或 active=False 不算阻塞
        nodes = [{"nodeId": "S12",
                  "guard": {"ownerTeamId": "BLUE", "defense": 0, "active": True}}]
        ws, _ = self._ws_with_blocks(nodes)
        changed, _, cur = main.block_diff(ws, {})
        self.assertEqual(changed, [])
        self.assertEqual(cur, {})


class TestContestFields(unittest.TestCase):
    def test_red_player(self):
        c = {"contestId": "C7", "contestType": "PASS", "redPlayerId": 1001,
             "bluePlayerId": 2222, "redPoint": 1, "bluePoint": 2,
             "roundIndex": 2, "cards": {"RED": "BING_ZHENG", "BLUE": "XIAN_GONG"}}
        f = main.contest_fields(None, c, 1001)
        self.assertEqual(f["contestId"], "C7")
        self.assertEqual(f["type"], "PASS")
        self.assertEqual(f["myPt"], 1)
        self.assertEqual(f["oppPt"], 2)
        self.assertEqual(f["myCard"], "BING_ZHENG")
        self.assertEqual(f["oppCard"], "XIAN_GONG")
        self.assertEqual(f["ri"], 2)

    def test_blue_player_swaps_points(self):
        c = {"contestId": "C7", "contestType": "PASS", "redPlayerId": 2222,
             "bluePlayerId": 1001, "redPoint": 1, "bluePoint": 2, "cards": {}}
        f = main.contest_fields(None, c, 1001)
        self.assertEqual(f["myPt"], 2)  # 我是蓝方，取 bluePoint
        self.assertEqual(f["oppPt"], 1)

    def test_missing_cards_none(self):
        c = {"contestId": "C7", "contestType": "TASK", "redPlayerId": 1001,
             "bluePlayerId": 2222}
        f = main.contest_fields(None, c, 1001)
        self.assertIsNone(f["myCard"])
        self.assertIsNone(f["oppCard"])


class TestRejectFields(unittest.TestCase):
    def test_rejected_action_extracted(self):
        ar = [{"playerId": 1001, "round": 4, "action": "MOVE",
               "targetNodeId": "S12", "accepted": False,
               "errorCode": "MOVE_BLOCKED_BY_GUARD"},
              {"playerId": 1001, "round": 4, "action": "SQUAD_CLEAR",
               "accepted": True}]
        ws = WorldState(_inquire(action_results=ar), player_id=1001)
        out = main.reject_fields_list(ws, 1001)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["action"], "MOVE")
        self.assertEqual(out[0]["target"], "S12")
        self.assertEqual(out[0]["code"], "MOVE_BLOCKED_BY_GUARD")
        self.assertEqual(out[0]["round"], 4)

    def test_no_rejection_empty(self):
        ar = [{"playerId": 1001, "round": 4, "accepted": True}]
        ws = WorldState(_inquire(action_results=ar), player_id=1001)
        self.assertEqual(main.reject_fields_list(ws, 1001), [])

    def test_other_player_ignored(self):
        ar = [{"playerId": 2222, "round": 4, "accepted": False, "errorCode": "X"}]
        ws = WorldState(_inquire(action_results=ar), player_id=1001)
        self.assertEqual(main.reject_fields_list(ws, 1001), [])


class TestBudgetFields(unittest.TestCase):
    def test_normal(self):
        f = main.budget_fields(72, 310, 600)
        self.assertEqual(f, {"round": 72, "est": 310, "left": 528})

    def test_none_skips(self):
        self.assertIsNone(main.budget_fields(72, None, 600))

    def test_inf_skips(self):
        self.assertIsNone(main.budget_fields(72, float("inf"), 600))

    def test_custom_duration(self):
        f = main.budget_fields(100, 200, 500)
        self.assertEqual(f["left"], 400)


class TestStartExtraFields(unittest.TestCase):
    def test_extracts_map_roles(self):
        # 构造一个最小 GameContext
        from strategy.decision import GameContext
        start_data = {
            "nodes": [{"nodeId": "S01", "type": "START"},
                      {"nodeId": "S14", "type": "GATE"},
                      {"nodeId": "S15", "type": "FINISH"}],
            "edges": [],
            "map": {"gameplay": {"roles": {"startNodeId": "S01",
                                            "gateNodeId": "S14",
                                            "terminalNodeIds": ["S15"]},
                                 "processNodes": [
                                     {"nodeId": "S02", "processType": "X", "processRound": 6},
                                     {"nodeId": "S05", "processType": "Y", "processRound": 4}]}}}
        ctx = GameContext(1001, "RED", 0, start_data)
        f = main.start_extra_fields(ctx)
        self.assertEqual(f["gate"], "S14")
        self.assertEqual(f["terminals"], ["S15"])
        self.assertEqual(f["processNodes"], ["S02", "S05"])

    def test_no_map_empty(self):
        from strategy.decision import GameContext
        ctx = GameContext(1001, "RED", 0, {})
        self.assertEqual(main.start_extra_fields(ctx), {})


if __name__ == "__main__":
    unittest.main()
