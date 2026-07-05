"""M5 对抗策略单测：阻塞路由/突破/窗口出牌/终局急策/小分队探路。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402

PID = 1001

# 线性地图：S01 - SB - S14(宫门) - S15(终点)。SB 为终段唯一通路（不可绕行）。
LINEAR = {
    "matchId": "c", "durationRound": 600,
    "nodes": [
        {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "SB", "type": "STATION", "x": 1, "y": 0},
        {"nodeId": "S14", "type": "GATE", "x": 2, "y": 0},
        {"nodeId": "S15", "type": "FINISH", "x": 3, "y": 0, "terminal": True},
    ],
    "edges": [
        {"fromNodeId": "S01", "toNodeId": "SB", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"fromNodeId": "SB", "toNodeId": "S14", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD", "distance": 20, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
    "processNodes": [],
}

# Y 型可绕行地图：S01 → (SL 或 SR) → SJ → S15。SL/SR 互为备选。
YMAP = {
    "matchId": "y", "durationRound": 600,
    "nodes": [
        {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "SL", "type": "STATION", "x": 1, "y": 1},
        {"nodeId": "SR", "type": "STATION", "x": 1, "y": -1},
        {"nodeId": "SJ", "type": "STATION", "x": 2, "y": 0},
        {"nodeId": "S15", "type": "FINISH", "x": 3, "y": 0, "terminal": True},
    ],
    "edges": [
        {"fromNodeId": "S01", "toNodeId": "SL", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"fromNodeId": "S01", "toNodeId": "SR", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"fromNodeId": "SL", "toNodeId": "SJ", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"fromNodeId": "SR", "toNodeId": "SJ", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"fromNodeId": "SJ", "toNodeId": "S15", "routeType": "ROAD", "distance": 20, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
    "processNodes": [],
}


def world(start_data, node="S01", state="IDLE", phase="NORMAL", verified=False, delivered=False,
          freshness=100.0, good=100, bad=0, resources=None, buffs=None, rush_used=0,
          nodes=None, tasks=None, contests=None, squad=0, gp=4, gm=None, rnd=20):
    inquire = {
        "round": rnd, "phase": phase,
        "players": [{"playerId": PID, "teamId": "RED", "state": state, "currentNodeId": node,
                     "verified": verified, "delivered": delivered, "goodFruit": good, "badFruit": bad,
                     "freshness": freshness, "resources": resources or {}, "buffs": buffs or [],
                     "rushTacticUsedCount": rush_used, "squadAvailable": squad, "guardActionPoint": gp}],
        "nodes": nodes or [], "tasks": tasks or [], "contests": contests or [], "events": [],
    }
    return WorldState(inquire, PID, gm)


def obstacle_node(nid):
    return {"nodeId": nid, "hasObstacle": True, "obstacleType": "ROCKFALL"}


def guard_node(nid, owner="BLUE", defense=4):
    return {"nodeId": nid, "guard": {"ownerTeamId": owner, "defense": defense, "active": True}}


class TestBlockRouting(unittest.TestCase):
    def test_reroute_around_obstacle(self):
        gm = GameMap(YMAP)
        eng = DecisionEngine(GameContext(PID, "RED", 0, YMAP))
        # 默认最短会经 SL（先定义），障碍放 SL → 应绕行经 SR
        w = world(YMAP, node="S01", nodes=[obstacle_node("SL")], gm=gm)
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "MOVE", "targetNodeId": "SR"})

    def test_path_avoids_blocked(self):
        gm = GameMap(YMAP)
        path, _ = gm.time_optimal_path("S01", "S15", blocked={"SL"})
        self.assertNotIn("SL", path)
        self.assertEqual(path[-1], "S15")


class TestBreakthroughObstacle(unittest.TestCase):
    def setUp(self):
        self.gm = GameMap(LINEAR)

    def eng(self):
        return DecisionEngine(GameContext(PID, "RED", 0, LINEAR))

    def test_clear_when_unavoidable(self):
        w = world(LINEAR, node="S01", nodes=[obstacle_node("SB")], gm=self.gm, good=100)
        a = self.eng().decide(w)[0]
        self.assertEqual(a, {"action": "CLEAR", "targetNodeId": "SB"})

    def test_t04_preferred_when_available(self):
        tasks = [{"taskId": "TZ", "taskTemplateId": "T04", "nodeId": "SB",
                  "processType": "CLEAR_OBSTACLE", "processRound": 6,
                  "active": True, "completed": False}]
        w = world(LINEAR, node="S01", nodes=[obstacle_node("SB")], tasks=tasks, gm=self.gm)
        a = self.eng().decide(w)[0]
        self.assertEqual(a, {"action": "CLAIM_TASK", "taskId": "TZ"})

    def test_forced_pass_when_low_fruit(self):
        w = world(LINEAR, node="S01", nodes=[obstacle_node("SB")], gm=self.gm, good=1)  # 好果不足以清障
        a = self.eng().decide(w)[0]
        self.assertEqual(a, {"action": "FORCED_PASS", "targetNodeId": "SB"})


class TestBreakthroughGuard(unittest.TestCase):
    def setUp(self):
        self.gm = GameMap(LINEAR)

    def eng(self):
        return DecisionEngine(GameContext(PID, "RED", 0, LINEAR))

    def test_break_guard_with_min_fruit(self):
        w = world(LINEAR, node="S01", nodes=[guard_node("SB", "BLUE", 4)], gm=self.gm, good=100)
        a = self.eng().decide(w)[0]
        self.assertEqual(a["action"], "BREAK_GUARD")
        self.assertEqual(a["targetNodeId"], "SB")
        self.assertGreaterEqual(a.get("goodFruit", 0) * 2 + a.get("badFruit", 0) * 3, 4)

    def test_break_order_bound_in_rush(self):
        w = world(LINEAR, node="S01", phase="RUSH", nodes=[guard_node("SB", "BLUE", 7)], gm=self.gm,
                  good=100, rush_used=0)
        a = self.eng().decide(w)[0]
        self.assertEqual(a["action"], "BREAK_GUARD")
        self.assertEqual(a.get("rushTactic"), "BREAK_ORDER")  # 2好果(4)+破关令(3)=7

    def test_forced_pass_when_cannot_afford(self):
        # 防守值 5：需 3 好果(>2 上限)或含坏果；无坏果、好果上限 2 → 攻坚值最多 4 <5 → 强制通行
        w = world(LINEAR, node="S01", nodes=[guard_node("SB", "BLUE", 5)], gm=self.gm, good=100, bad=0)
        a = self.eng().decide(w)[0]
        self.assertEqual(a, {"action": "FORCED_PASS", "targetNodeId": "SB"})


class TestWindowCard(unittest.TestCase):
    def setUp(self):
        self.gm = GameMap(LINEAR)

    def test_bing_zheng_lead_on_high_stakes(self):
        # 高筹码(GATE)第 1 拍、无对手信息 → 领出强牌 BING_ZHENG（护卫点用于高筹码窗口）
        c = [{"contestId": "C1", "contestType": "GATE", "roundIndex": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"})

    def test_bing_on_low_stakes_when_guard_ample(self):
        # Iter19：低筹码(RESOURCE) guard 充足(gp=4 > LOW_STAKES_RESERVE=2)时解禁 BING——
        # 红方不领过所、马只 1 匹，stakes1 下 BING 是唯一能赢/平的牌，不再 ABSTAIN 必输
        c = [{"contestId": "C1", "contestType": "RESOURCE", "roundIndex": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm, gp=4)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"})

    def test_no_bing_on_low_stakes_when_guard_reserved(self):
        # 低筹码 guard 不足(gp=2 ≤ LOW_STAKES_RESERVE=2)→ 保留给中/高筹码窗口，弃权
        c = [{"contestId": "C1", "contestType": "RESOURCE", "roundIndex": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm, gp=2)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"})

    def test_reactive_counter_on_beat2(self):
        # 第 2 拍：对手上拍出 BING_ZHENG → 我方反制 XIAN_GONG（唯一克星），高筹码舍得花好果
        c = [{"contestId": "C1", "contestType": "GATE", "roundIndex": 2, "redPoint": 0, "bluePoint": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False,
              "cards": {"RED": "BING_ZHENG", "BLUE": "BING_ZHENG"}}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm, good=100)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"})

    def test_reactive_qiang_counters_xian(self):
        # 对手上拍出 XIAN_GONG → 唯一克星 QIANG_XING；骑马增益时免消耗，低筹码也愿出
        c = [{"contestId": "C1", "contestType": "RESOURCE", "roundIndex": 2, "redPoint": 0, "bluePoint": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False,
              "cards": {"RED": "ABSTAIN", "BLUE": "XIAN_GONG"}}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm,
                  buffs=[{"type": "FAST_HORSE", "remainingRound": 5}])
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "QIANG_XING"})

    def test_abstain_when_already_won(self):
        # 我方已 2 胜点 → 第 3 拍弃权省成本
        c = [{"contestId": "C1", "contestType": "GATE", "roundIndex": 3, "redPoint": 2, "bluePoint": 0,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm, gp=4)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"})

    def test_task_window_uses_bing_when_low_fresh(self):
        # Iter17 核心修正：TASK 中筹码、鲜度<80(XIAN 不可用) → 解禁 BING 领出，非弃权
        c = [{"contestId": "C1", "contestType": "TASK", "roundIndex": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm, gp=4, freshness=70.0)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"})

    def test_tie_with_bing_when_opp_leads_bing_low_fresh(self):
        # 鲜度<80、对手上拍 BING：唯一克星 XIAN 不可用 → 出同牌 BING 求平，非弃权白送胜点
        c = [{"contestId": "C1", "contestType": "TASK", "roundIndex": 2, "redPoint": 0, "bluePoint": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False,
              "cards": {"RED": "BING_ZHENG", "BLUE": "BING_ZHENG"}}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm, gp=4, freshness=70.0)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"})

    def test_no_abstain_when_guard_below_reserve(self):
        # TASK 鲜度<80、护卫点=1(≤reserve=1)→ BING 被禁；但有文书时出 YAN 争取赢，而非弃权
        c = [{"contestId": "C1", "contestType": "TASK", "roundIndex": 2, "redPoint": 0, "bluePoint": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False,
              "cards": {"RED": "BING_ZHENG", "BLUE": "BING_ZHENG"}}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm,
                  gp=1, freshness=70.0, resources={"PASS_TOKEN": 1})
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a["card"], "YAN_DIE")  # 不弃权，出最强可用牌

    def test_gate_uses_bing_with_last_guard(self):
        # GATE 关键窗口：护卫点仅剩 1 仍出 BING（不预留）
        c = [{"contestId": "C1", "contestType": "GATE", "roundIndex": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm, gp=1, freshness=70.0)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"})

    def test_resource_window_bing_when_guard_ample_low_fresh(self):
        # Iter19：RESOURCE 低筹码、guard 充足(gp=4)、鲜度低(70) → 仍出 BING（BING 不需鲜度，
        # 是低筹码下唯一能赢/平的牌）。鲜度只影响 XIAN，不影响 BING 解禁。
        c = [{"contestId": "C1", "contestType": "RESOURCE", "roundIndex": 1,
              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}]
        w = world(LINEAR, node="SB", state="CONTESTING", contests=c, gm=self.gm, gp=4, freshness=70.0)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"})


class TestEndgameTactic(unittest.TestCase):
    def setUp(self):
        self.gm = GameMap(LINEAR)

    def eng(self):
        return DecisionEngine(GameContext(PID, "RED", 0, LINEAR))

    def test_rush_protect_when_low_fresh(self):
        w = world(LINEAR, node="SB", phase="RUSH", freshness=80.0, gm=self.gm)
        self.assertEqual(self.eng().decide(w)[0], {"action": "RUSH_PROTECT"})

    def test_rush_speed_when_far_and_healthy_no_horse(self):
        # SB→S15 距离 40 > 30 判为"远"，鲜度健康且无马 → 疾行令
        w = world(LINEAR, node="SB", phase="RUSH", freshness=100.0, gm=self.gm)
        self.assertEqual(self.eng().decide(w)[0], {"action": "RUSH_SPEED"})

    def test_no_rush_speed_when_holding_horse(self):
        w = world(LINEAR, node="SB", phase="RUSH", freshness=100.0, resources={"FAST_HORSE": 1}, gm=self.gm)
        self.assertNotEqual(self.eng().decide(w)[0].get("action"), "RUSH_SPEED")


class TestSquadScout(unittest.TestCase):
    def test_scout_gate_when_near_and_have_squad(self):
        gm = GameMap(LINEAR)
        # 在 SB：到宫门 S14 帧数在 [8,40] 窗口内 → 派探路宫门
        w = world(LINEAR, node="SB", squad=8, gm=gm)
        acts = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)
        squad = [a for a in acts if a["action"] == "SQUAD_SCOUT"]
        self.assertEqual(squad, [{"action": "SQUAD_SCOUT", "targetNodeId": "S14"}])

    def test_no_scout_when_no_squad(self):
        gm = GameMap(LINEAR)
        w = world(LINEAR, node="SB", squad=0, gm=gm)
        acts = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)
        self.assertFalse([a for a in acts if a["action"] == "SQUAD_SCOUT"])


# 天气路由测试图：水路(SW)与官道(SR)两条平行路线，距离相同。
# 无天气时水路耗时系数更低(1250<1380)→走水路；暴雨命中水路(×1350)→水路变慢→走官道。
WMAP = {
    "matchId": "w", "durationRound": 600,
    "nodes": [
        {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "SW", "type": "STATION", "x": 1, "y": 1},
        {"nodeId": "SR", "type": "STATION", "x": 1, "y": -1},
        {"nodeId": "S15", "type": "FINISH", "x": 2, "y": 0, "terminal": True},
    ],
    "edges": [
        {"fromNodeId": "S01", "toNodeId": "SW", "routeType": "WATER", "distance": 8, "bidirectional": True},
        {"fromNodeId": "SW", "toNodeId": "S15", "routeType": "WATER", "distance": 8, "bidirectional": True},
        {"fromNodeId": "S01", "toNodeId": "SR", "routeType": "ROAD", "distance": 8, "bidirectional": True},
        {"fromNodeId": "SR", "toNodeId": "S15", "routeType": "ROAD", "distance": 8, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
    "processNodes": [],
}


class TestWeatherRouting(unittest.TestCase):
    def test_water_route_without_weather(self):
        gm = GameMap(WMAP)
        path, _ = gm.time_optimal_path("S01", "S15")
        self.assertEqual(path, ["S01", "SW", "S15"])  # 水路更快

    def test_avoids_water_in_heavy_rain(self):
        gm = GameMap(WMAP)
        path, _ = gm.time_optimal_path("S01", "S15", weather_type="HEAVY_RAIN")
        self.assertEqual(path, ["S01", "SR", "S15"])  # 暴雨 penalize 水路→改走官道

    def test_fog_does_not_affect_road(self):
        gm = GameMap(WMAP)
        path, _ = gm.time_optimal_path("S01", "S15", weather_type="MOUNTAIN_FOG")
        self.assertEqual(path, ["S01", "SW", "S15"])  # 山雾不影响水路/官道


class TestWindowCardWithMain(unittest.TestCase):
    def test_window_card_keeps_moving(self):
        # PASS 守方被动参战：移动中同时持有未结算窗口 → 边出牌边续行，不再丢弃主车队动作
        gm = GameMap(LINEAR)
        c = [{"contestId": "C1", "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}]
        w = world(LINEAR, node="SB", state="MOVING", contests=c, gm=gm, squad=0, gp=4)
        w.me.next_node_id = "S14"
        acts = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)
        kinds = [a["action"] for a in acts]
        self.assertIn("MOVE", kinds)
        self.assertIn("WINDOW_CARD", kinds)


class TestVerifyBreakOrder(unittest.TestCase):
    def test_break_order_on_verify_when_healthy_and_bad_fruit(self):
        gm = GameMap(LINEAR)
        w = world(LINEAR, node="S14", phase="RUSH", verified=False, freshness=100.0, bad=2,
                  rush_used=0, gm=gm)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "VERIFY_GATE", "rushTactic": "BREAK_ORDER"})

    def test_no_break_order_when_low_freshness(self):
        # 鲜度低 → 急策额度留给护果令保鲜，不绑定破关令
        gm = GameMap(LINEAR)
        w = world(LINEAR, node="S14", phase="RUSH", verified=False, freshness=80.0, bad=2,
                  rush_used=0, gm=gm)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "RUSH_PROTECT"})

    def test_no_break_order_without_bad_fruit(self):
        # 无坏果时不损耗好果分换区区 3 帧验核
        gm = GameMap(LINEAR)
        w = world(LINEAR, node="S14", phase="RUSH", verified=False, freshness=100.0, bad=0,
                  rush_used=0, gm=gm)
        a = DecisionEngine(GameContext(PID, "RED", 0, LINEAR)).decide(w)[0]
        self.assertEqual(a, {"action": "VERIFY_GATE"})


if __name__ == "__main__":
    unittest.main()