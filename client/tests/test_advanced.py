"""M7 能力补全单测：拒绝反馈/情报/绕行-清障权衡/绕路做任务/防御性小分队/主动设卡(flag)。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402

PID = 1001


def _map(nodes, edges, roles=None, process=None):
    return {
        "matchId": "a", "durationRound": 600,
        "nodes": nodes, "edges": edges,
        "map": {"gameplay": {"roles": roles or {}}},
        "processNodes": process or [],
    }


def _node(nid, typ="STATION", start=False, terminal=False):
    return {"nodeId": nid, "type": typ, "x": 0, "y": 0, "start": start, "terminal": terminal}


def _edge(a, b, dist=10, rt="ROAD"):
    return {"fromNodeId": a, "toNodeId": b, "routeType": rt, "distance": dist, "bidirectional": True}


def world(sd, gm, node, state="IDLE", phase="NORMAL", verified=False, delivered=False,
          freshness=100.0, good=100, bad=0, resources=None, buffs=None, rush_used=0,
          nodes=None, tasks=None, contests=None, squad=0, gp=4, rnd=20,
          score=0, opp_node=None, opp_score=0, opp_delivered=False, opp_retired=False,
          opp_team="BLUE"):
    players = [{"playerId": PID, "teamId": "RED", "state": state, "currentNodeId": node,
                "verified": verified, "delivered": delivered, "goodFruit": good, "badFruit": bad,
                "freshness": freshness, "resources": resources or {}, "buffs": buffs or [],
                "rushTacticUsedCount": rush_used, "squadAvailable": squad, "guardActionPoint": gp,
                "totalScore": score}]
    if opp_node is not None:
        players.append({"playerId": 2222, "teamId": opp_team, "state": "IDLE",
                        "currentNodeId": opp_node, "verified": False, "delivered": opp_delivered,
                        "retired": opp_retired, "goodFruit": 100, "badFruit": 0, "freshness": 100.0,
                        "resources": {}, "buffs": [], "squadAvailable": 0, "guardActionPoint": 4,
                        "totalScore": opp_score})
    inquire = {
        "round": rnd, "phase": phase,
        "players": players,
        "nodes": nodes or [], "tasks": tasks or [], "contests": contests or [], "events": [],
    }
    return WorldState(inquire, PID, gm)


# 线性 S01-SA(处理点)-S14-S15
LINEAR = _map(
    [_node("S01", "START", start=True), _node("SA"), _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
    [_edge("S01", "SA"), _edge("SA", "S14"), _edge("S14", "S15")],
    {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
    [{"nodeId": "SA", "processType": "TRANSFER", "processRound": 4}],
)

# Y 型：S01→(SL|SR)→SJ→S15
YMAP = _map(
    [_node("S01", "START", start=True), _node("SL"), _node("SR"), _node("SJ"), _node("S15", "FINISH", terminal=True)],
    [_edge("S01", "SL"), _edge("S01", "SR"), _edge("SL", "SJ"), _edge("SR", "SJ"), _edge("SJ", "S15")],
    {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
)


class TestRejectionFeedback(unittest.TestCase):
    def test_process_required_forces_process(self):
        gm = GameMap(LINEAR)
        eng = DecisionEngine(GameContext(PID, "RED", 0, LINEAR))
        eng._last_main_action = {"action": "MOVE", "targetNodeId": "S14"}
        eng._processed_here = True  # 误以为已处理
        w = world(LINEAR, gm, "SA", rnd=21, nodes=[{"nodeId": "SA"}])
        w.action_results = [{"playerId": PID, "round": 20, "action": "MOVE",
                             "accepted": False, "errorCode": "PROCESS_REQUIRED"}]
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "PROCESS"})

    def test_move_block_cooldowns_target_and_reroutes(self):
        gm = GameMap(YMAP)
        eng = DecisionEngine(GameContext(PID, "RED", 0, YMAP))
        eng._last_main_action = {"action": "MOVE", "targetNodeId": "SL"}
        w = world(YMAP, gm, "S01", rnd=21)
        w.action_results = [{"playerId": PID, "round": 20, "action": "MOVE",
                             "accepted": False, "errorCode": "MOVE_BLOCKED_BY_GUARD"}]
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "MOVE", "targetNodeId": "SR"})  # 绕开被拉黑的 SL


class TestRejectionFeedbackIter20(unittest.TestCase):
    """Iter20：拒绝反馈全覆盖——task/window/busy/conflict 各码不再裸奔空转。"""

    def _eng(self, sd):
        return DecisionEngine(GameContext(PID, "RED", 0, sd))

    def test_task_requirement_not_met_blacklists_task(self):
        # CLAIM_TASK 被拒(TASK_REQUIREMENT_NOT_MET) → taskId 进黑名单 → 不再当帧重发 CLAIM_TASK
        gm = GameMap(LINEAR)
        eng = self._eng(LINEAR)
        eng._last_main_action = {"action": "CLAIM_TASK", "taskId": "TK"}
        w = world(LINEAR, gm, "SA", rnd=21,
                  tasks=[{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA",
                          "processRound": 3, "active": True, "completed": False}],
                  nodes=[{"nodeId": "SA"}])
        w.action_results = [{"playerId": PID, "round": 20, "action": "CLAIM_TASK",
                             "accepted": False, "errorCode": "TASK_REQUIREMENT_NOT_MET"}]
        eng._apply_rejection_feedback(w)
        self.assertIn("TK", eng._task_blacklist)
        # 下一帧 _maybe_task 跳过黑名单任务 → 不再产出 CLAIM_TASK
        w2 = world(LINEAR, gm, "SA", rnd=21,
                   tasks=[{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "SA",
                           "processRound": 3, "active": True, "completed": False}],
                   nodes=[{"nodeId": "SA"}])
        acts = eng.decide(w2)
        self.assertTrue(all(a.get("action") != "CLAIM_TASK" for a in acts))

    def test_window_draw_retry_abstains_contest(self):
        # WINDOW_DRAW_RETRY_LIMIT → 该窗口弃权，不再出 WINDOW_CARD
        gm = GameMap(LINEAR)
        eng = self._eng(LINEAR)
        eng._last_window_cid = "C1"
        w = world(LINEAR, gm, "SA", rnd=21,
                  contests=[{"contestId": "C1", "contestType": "DOCK", "roundIndex": 1,
                             "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}],
                  nodes=[{"nodeId": "SA"}])
        w.action_results = [{"playerId": PID, "round": 20, "action": "WINDOW_CARD",
                             "accepted": False, "errorCode": "WINDOW_DRAW_RETRY_LIMIT"}]
        eng._apply_rejection_feedback(w)
        self.assertTrue(eng._is_contest_abstained(w, "C1"))
        # 弃权窗口不出牌
        w2 = world(LINEAR, gm, "SA", rnd=21,
                   contests=[{"contestId": "C1", "contestType": "DOCK", "roundIndex": 2,
                              "redPlayerId": PID, "bluePlayerId": 2222, "resolved": False}],
                   nodes=[{"nodeId": "SA"}])
        acts = eng.decide(w2)
        self.assertTrue(all(a.get("action") != "WINDOW_CARD" for a in acts))

    def test_object_busy_blacklists_claim_node(self):
        # CLAIM_RESOURCE 撞 OBJECT_BUSY → 节点忙冷却 → _maybe_claim 跳过
        gm = GameMap(LINEAR)
        eng = self._eng(LINEAR)
        eng._last_main_action = {"action": "CLAIM_RESOURCE", "targetNodeId": "SA",
                                 "resourceType": "ICE_BOX"}
        w = world(LINEAR, gm, "SA", rnd=21,
                  nodes=[{"nodeId": "SA", "resourceStock": {"ICE_BOX": 1}}])
        w.action_results = [{"playerId": PID, "round": 20, "action": "CLAIM_RESOURCE",
                             "accepted": False, "errorCode": "OBJECT_BUSY"}]
        eng._apply_rejection_feedback(w)
        self.assertTrue(eng._is_node_busy(w, "SA"))

    def test_invalid_action_conflict_backs_off(self):
        # INVALID_ACTION_CONFLICT → 主动作退避 1 帧
        gm = GameMap(LINEAR)
        eng = self._eng(LINEAR)
        eng._last_main_action = {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}
        w = world(LINEAR, gm, "SA", rnd=21, nodes=[{"nodeId": "SA"}])
        w.action_results = [{"playerId": PID, "round": 20, "action": "USE_RESOURCE",
                             "accepted": False, "errorCode": "INVALID_ACTION_CONFLICT"}]
        eng._apply_rejection_feedback(w)
        self.assertTrue(eng._is_action_blocked(w, "USE_RESOURCE"))


class TestProtocolActionQuota(unittest.TestCase):
    """Iter20 P1：协议§4.1 每帧≤1 主车队动作，杜绝 [horse, MOVE] 式非法并发。"""

    def test_keep_moving_horse_is_single_action(self):
        # 边距 20：SA→S15=40 > 30，远到值得用马
        sd = _map(
            [_node("S01", "START", start=True), _node("SA"), _node("S14", "GATE"),
             _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SA", 20), _edge("SA", "S14", 20), _edge("S14", "S15", 20)],
            {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(sd)
        eng = DecisionEngine(GameContext(PID, "RED", 0, sd))
        w = world(sd, gm, "SA", state="MOVING", freshness=100.0,
                  resources={"FAST_HORSE": 1})
        w.me.next_node_id = "S14"
        acts = eng.decide(w)
        # 用马时只产出 USE_RESOURCE，绝不同帧并发 MOVE（旧 [horse, MOVE] 非法）
        self.assertEqual([a.get("action") for a in acts], ["USE_RESOURCE"])

    def test_dedup_drops_second_main_action(self):
        eng = DecisionEngine(GameContext(PID, "RED", 0, LINEAR))
        # 模拟控制流意外产出 2 个主车队动作 + 1 窗口牌 + 1 小分队
        raw = [
            {"action": "USE_RESOURCE", "resourceType": "ICE_BOX"},
            {"action": "MOVE", "targetNodeId": "S14"},
            {"action": "WINDOW_CARD", "contestId": "C1", "card": "ABSTAIN"},
            {"action": "SQUAD_SCOUT", "targetNodeId": "S14"},
        ]
        out = eng._dedup_actions(raw)
        mains = [a for a in out if a["action"] in eng._MAIN_ACTION_TYPES]
        self.assertEqual(len(mains), 1)
        self.assertEqual(mains[0]["action"], "USE_RESOURCE")  # 保留首个
        # 窗口与小分队不受影响
        self.assertEqual(len([a for a in out if a["action"] == "WINDOW_CARD"]), 1)
        self.assertEqual(len([a for a in out if a["action"].startswith("SQUAD_")]), 1)


class TestDeliveryPanic(unittest.TestCase):
    """Iter20 P2：交付告急时禁用绕路、直奔宫门→终点。"""

    def test_panic_skips_task_detour(self):
        # 临近超时：est + 余量 > 剩余 → 告急，不再为旁路任务绕路，直奔宫门
        m = _map(
            [_node("S01", "START", start=True), _node("SA"), _node("ST"), _node("SJ"),
             _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SA", 10), _edge("SA", "SJ", 10), _edge("S01", "ST", 10),
             _edge("ST", "SJ", 10), _edge("SJ", "S14", 10), _edge("S14", "S15", 10)],
            {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "ST", "processRound": 3,
                  "active": True, "completed": False}]
        # rnd=560，剩余 40 帧；S01→S15 直达约 50+ 帧 → 告急
        w = world(m, gm, "S01", rnd=560, tasks=tasks)
        a = eng.decide(w)[0]
        self.assertNotEqual(a.get("targetNodeId"), "ST")  # 不绕去任务节点
        self.assertEqual(a.get("action"), "MOVE")


class TestRushNoDetour(unittest.TestCase):
    """Iter20 P3a/b：RUSH 阶段禁绕路、遇阻优先就地突破。"""

    def test_rush_skips_task_detour(self):
        # RUSH 阶段（已验核，前往终点）：即便旁路有任务也不绕路，直奔终点
        m = _map(
            [_node("S01", "START", start=True), _node("SA"), _node("ST"), _node("SJ"),
             _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SA", 10), _edge("SA", "SJ", 10), _edge("S01", "ST", 10),
             _edge("ST", "SJ", 10), _edge("SJ", "S14", 10), _edge("S14", "S15", 10)],
            {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "ST", "processRound": 3,
                  "active": True, "completed": False}]
        # RUSH + 已验核 + 在 S14（前往 S15），时间充足不告急
        w = world(m, gm, "S14", phase="RUSH", verified=True, rnd=460, tasks=tasks)
        a = eng.decide(w)[0]
        self.assertNotEqual(a.get("targetNodeId"), "ST")  # RUSH 不绕去任务
        self.assertEqual(a.get("action"), "MOVE")


class TestBreakGuardCost(unittest.TestCase):
    """Iter20 P3c：_enter_cost_fn 对可破敌卡计入好果机会成本（不再返回 0）。"""

    def test_breakable_guard_cost_includes_good_fruit(self):
        m = _map(
            [_node("S01", "START", start=True), _node("S10", "KEY_PASS"), _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "S10", 10), _edge("S10", "S15", 10)],
            {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        # S10 蓝方设卡 defense=4 active；本方 100 好果 0 坏果，可破（2 好果×2=4≥4）
        w = world(m, gm, "S01", good=100, bad=0,
                  nodes=[{"nodeId": "S10",
                          "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}}])
        fn = eng._enter_cost_fn(w, w.me)
        cost = fn("S10")
        # defense=4，无坏果、无破关令 → 需 2 好果；2×BREAK_GUARD_GOOD_FRAME_EQ(6)=12（旧版返回 0）
        self.assertEqual(cost, 2 * config.BREAK_GUARD_GOOD_FRAME_EQ)

    def test_break_good_needed_helper(self):
        eng = DecisionEngine(GameContext(PID, "RED", 0, LINEAR))
        me = type("M", (), {"bad_fruit": 0})()
        self.assertEqual(eng._break_good_needed(0, 0, me), 0)   # 无防守
        self.assertEqual(eng._break_good_needed(4, 0, me), 2)   # 4→2 好果
        self.assertEqual(eng._break_good_needed(3, 0, me), 2)   # ceil(3/2)=2
        self.assertEqual(eng._break_good_needed(2, 0, me), 1)   # 1 好果
        me3 = type("M", (), {"bad_fruit": 2})()
        self.assertEqual(eng._break_good_needed(6, 0, me3), 0)   # 2 坏果×3=6 全覆盖
        self.assertEqual(eng._break_good_needed(7, 3, me3), 0)   # bo3 + 坏6 = 9 ≥ 7 → 0 好果


class TestIntel(unittest.TestCase):
    def test_use_intel_on_gate_within_range(self):
        gm = GameMap(LINEAR)  # SA→S14 距离 10 ≤15
        eng = DecisionEngine(GameContext(PID, "RED", 0, LINEAR))
        eng._stay_node = "SA"
        eng._processed_here = True  # SA 已处理，进入后续
        w = world(LINEAR, gm, "SA", resources={"INTEL": 1}, nodes=[{"nodeId": "SA"}])
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "USE_RESOURCE", "resourceType": "INTEL", "targetNodeId": "S14"})

    def test_no_intel_when_out_of_range(self):
        far = _map(
            [_node("S01", "START", start=True), _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "S14", dist=20), _edge("S14", "S15")],  # S01→S14 距离 20 >15
            {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(far)
        eng = DecisionEngine(GameContext(PID, "RED", 0, far))
        w = world(far, gm, "S01", resources={"INTEL": 1})
        a = eng.decide(w)[0]
        self.assertNotEqual(a.get("action"), "USE_RESOURCE")


class TestRerouteVsClear(unittest.TestCase):
    def test_clear_when_reroute_far_more_costly(self):
        # 经 SL 很短(各10)，经 SR 很长(各60)；SL 有障碍 → 就地清障 SL 比绕远 SR 便宜
        m = _map(
            [_node("S01", "START", start=True), _node("SL"), _node("SR"), _node("SJ"),
             _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SL", 10), _edge("SL", "SJ", 10),
             _edge("S01", "SR", 60), _edge("SR", "SJ", 60), _edge("SJ", "S15", 10)],
            {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "S01", good=100, nodes=[{"nodeId": "SL", "hasObstacle": True}])
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "CLEAR", "targetNodeId": "SL"})


class TestTaskDetour(unittest.TestCase):
    def test_detour_to_offroute_task(self):
        # 菱形：直达经 SA(先定义→默认路径)，任务在 ST(等距旁路) → 绕去 ST 只多 processRound
        m = _map(
            [_node("S01", "START", start=True), _node("SA"), _node("ST"), _node("SJ"),
             _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SA"), _edge("SA", "SJ"), _edge("S01", "ST"), _edge("ST", "SJ"), _edge("SJ", "S15")],
            {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "ST", "processRound": 3,
                  "active": True, "completed": False}]
        w = world(m, gm, "S01", tasks=tasks)
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "MOVE", "targetNodeId": "ST"})  # 绕去任务节点

    def test_no_detour_when_task_score_enough(self):
        # 与上同图，但任务分已≥TASK_SEEK_TARGET(180)：不绕路，直达（走默认 SA）
        m = _map(
            [_node("S01", "START", start=True), _node("SA"), _node("ST"), _node("SJ"),
             _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SA"), _edge("SA", "SJ"), _edge("S01", "ST"), _edge("ST", "SJ"), _edge("SJ", "S15")],
            {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "ST", "processRound": 3,
                  "active": True, "completed": False}]
        w = world(m, gm, "S01", tasks=tasks)
        w.me.task_score = config.TASK_SEEK_TARGET
        a = eng.decide(w)[0]
        self.assertEqual(a["targetNodeId"], "SA")

    def test_detour_when_below_new_cap(self):
        # P1：任务分 90（旧上限）但仍 < 新上限 180 → 仍绕路做任务
        m = _map(
            [_node("S01", "START", start=True), _node("SA"), _node("ST"), _node("SJ"),
             _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SA"), _edge("SA", "SJ"), _edge("S01", "ST"), _edge("ST", "SJ"), _edge("SJ", "S15")],
            {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "ST", "processRound": 3,
                  "active": True, "completed": False}]
        w = world(m, gm, "S01", tasks=tasks)
        w.me.task_score = 90
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "MOVE", "targetNodeId": "ST"})

    def test_no_detour_at_score_cap_130(self):
        # Iter16：任务分封顶点 = 基础分 130（130+里程碑50=180）。base=130 → 不再绕路做任务
        m = _map(
            [_node("S01", "START", start=True), _node("SA"), _node("ST"), _node("SJ"),
             _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SA"), _edge("SA", "SJ"), _edge("S01", "ST"), _edge("ST", "SJ"), _edge("SJ", "S15")],
            {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
        )
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        tasks = [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "ST", "processRound": 3,
                  "active": True, "completed": False}]
        w = world(m, gm, "S01", tasks=tasks)
        w.me.task_score = 130  # 130+50=180 封顶，再做事零分收益
        a = eng.decide(w)[0]
        self.assertEqual(a["targetNodeId"], "SA")  # 直达，不绕路

    def test_detour_to_t06_with_horse(self):
        # Iter16：T06 需消耗马；持有马时绕路做 T06（+30 分），无马时不绕
        m = _map(
            [_node("S01", "START", start=True), _node("SA"), _node("ST"), _node("SJ"),
             _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SA"), _edge("SA", "SJ"), _edge("S01", "ST"), _edge("ST", "SJ"), _edge("SJ", "S15")],
            {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
            process=[],
        )
        m["taskTemplates"] = [
            {"taskTemplateId": "T06", "score": 30, "processRound": 3,
             "requiredResourceTypes": ["FAST_HORSE", "SHORT_HORSE"]},
        ]
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        tasks = [{"taskId": "TK", "taskTemplateId": "T06", "nodeId": "ST", "processRound": 3,
                  "active": True, "completed": False}]
        # 持有快马 → 绕路做 T06
        w = world(m, gm, "S01", tasks=tasks, resources={"FAST_HORSE": 1})
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "MOVE", "targetNodeId": "ST"})
        # 无马 → 不绕路做 T06
        w2 = world(m, gm, "S01", tasks=tasks, resources={})
        a2 = eng.decide(w2)[0]
        self.assertEqual(a2["targetNodeId"], "SA")


class TestDefensiveSquad(unittest.TestCase):
    def _chain(self):
        return _map(
            [_node("S01", "START", start=True), _node("SB"), _node("SC"), _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SB"), _edge("SB", "SC"), _edge("SC", "S15")],
            {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
        )

    def test_squad_clear_obstacle_ahead(self):
        m = self._chain()
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "S01", squad=8, nodes=[{"nodeId": "SC", "hasObstacle": True}])
        acts = eng.decide(w)
        self.assertIn({"action": "SQUAD_CLEAR", "targetNodeId": "SC"}, acts)

    def test_squad_weaken_guard_ahead(self):
        m = self._chain()
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "S01", squad=8,
                  nodes=[{"nodeId": "SC", "guard": {"ownerTeamId": "BLUE", "defense": 4, "active": True}}])
        acts = eng.decide(w)
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "SC"}, acts)


class TestOffensiveGuard(unittest.TestCase):
    """智能进攻设卡：仅在对手必经咽喉点、预算充足、未领先时种卡。"""

    def _keypass_map(self):
        return _map(
            [_node("S01", "START", start=True), _node("SK", "KEY_PASS"),
             _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SK"), _edge("SK", "S14"), _edge("S14", "S15")],
            {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
        )

    def test_set_guard_when_behind_and_opp_must_pass(self):
        # 对手在 S01（必经 SK），双方同分（不领先）→ 在 SK 种卡
        m = self._keypass_map()
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "SK", good=100, opp_node="S01", opp_score=0, score=0)
        self.assertEqual(eng.decide(w)[0],
                         {"action": "SET_GUARD", "targetNodeId": "SK", "extraGoodFruit": 1})

    def test_skip_when_leading(self):
        # 领先对手 → 回避设卡（防送破关悬赏）
        m = self._keypass_map()
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "SK", good=100, opp_node="S01", opp_score=0, score=10)
        self.assertNotEqual(eng.decide(w)[0].get("action"), "SET_GUARD")

    def test_skip_when_opp_already_passed(self):
        # 对手已越过 SK（在 S14）→ 不种卡
        m = self._keypass_map()
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "SK", good=100, opp_node="S14", opp_score=0, score=0)
        self.assertNotEqual(eng.decide(w)[0].get("action"), "SET_GUARD")

    def test_skip_when_disabled(self):
        m = self._keypass_map()
        gm = GameMap(m)
        old = config.OFFENSIVE_ENABLED
        config.OFFENSIVE_ENABLED = False
        try:
            eng = DecisionEngine(GameContext(PID, "RED", 0, m))
            w = world(m, gm, "SK", good=100, opp_node="S01", opp_score=0, score=0)
            self.assertNotEqual(eng.decide(w)[0].get("action"), "SET_GUARD")
        finally:
            config.OFFENSIVE_ENABLED = old

    def test_skip_when_good_fruit_low(self):
        # 好果不足以保留交付分 → 不种卡
        m = self._keypass_map()
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "SK", good=config.OFFENSIVE_GOOD_FRUIT_KEEP,
                  opp_node="S01", opp_score=0, score=0)
        self.assertNotEqual(eng.decide(w)[0].get("action"), "SET_GUARD")


class TestSquadReinforce(unittest.TestCase):
    """种卡后用小分队增援己方有效设卡（+2防守，不耗好果）。"""

    def _keypass_map(self):
        return _map(
            [_node("S01", "START", start=True), _node("SK", "KEY_PASS"),
             _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
            [_edge("S01", "SK"), _edge("SK", "S14"), _edge("S14", "S15")],
            {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
        )

    def test_reinforce_own_guard_below_cap(self):
        # 己方 SK 设卡 defense=4（< key_pass 上限 7），无前方阻塞，squad≥2 → 增援
        m = self._keypass_map()
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "SK", squad=8, verified=True,
                  nodes=[{"nodeId": "SK",
                          "guard": {"ownerTeamId": "RED", "defense": 4, "active": True}}])
        # verified=True 且在 SK：不会触发种卡（己方已有设卡占用），主车队应继续推进；
        # 小分队动作独立产出 → SQUAD_REINFORCE SK
        acts = eng.decide(w)
        self.assertIn({"action": "SQUAD_REINFORCE", "targetNodeId": "SK"}, acts)

    def test_no_reinforce_when_at_cap(self):
        # 防守值已顶满（key_pass=7）→ 不增援
        m = self._keypass_map()
        gm = GameMap(m)
        eng = DecisionEngine(GameContext(PID, "RED", 0, m))
        w = world(m, gm, "SK", squad=8, verified=True,
                  nodes=[{"nodeId": "SK",
                          "guard": {"ownerTeamId": "RED", "defense": 7, "active": True}}])
        acts = eng.decide(w)
        self.assertNotIn({"action": "SQUAD_REINFORCE", "targetNodeId": "SK"}, acts)


# 线性无处理点：S01-SB-S14-S15
LIN2 = _map(
    [_node("S01", "START", start=True), _node("SB"), _node("S14", "GATE"), _node("S15", "FINISH", terminal=True)],
    [_edge("S01", "SB"), _edge("SB", "S14"), _edge("S14", "S15")],
    {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
)


class TestNeverStuck(unittest.TestCase):
    """真实败局：卡在 S14/WAITING 空等至 600 帧。核心：移动中/等待中必须主动续行，绝不空等。"""

    def _eng(self):
        return DecisionEngine(GameContext(PID, "RED", 0, LIN2))

    def test_moving_reissues_move_to_target(self):
        gm = GameMap(LIN2)
        w = world(LIN2, gm, "SB", state="MOVING")
        w.me.next_node_id = "S14"
        self.assertEqual(self._eng().decide(w)[0], {"action": "MOVE", "targetNodeId": "S14"})

    def test_waiting_on_edge_resumes_not_stuck(self):
        # 在 S14->S15 边上被动等待：重发 MOVE S15 恢复前进（正是败局中缺失的动作）
        gm = GameMap(LIN2)
        w = world(LIN2, gm, "S14", state="WAITING", verified=True)
        w.me.next_node_id = "S15"
        self.assertEqual(self._eng().decide(w)[0], {"action": "MOVE", "targetNodeId": "S15"})

    def test_waiting_at_gate_replans_and_verifies(self):
        # 被动等待且无在途目标(停在宫门)、RUSH、未验核 → 重规划并验核，而非空等
        gm = GameMap(LIN2)
        w = world(LIN2, gm, "S14", state="WAITING", phase="RUSH", verified=False)
        self.assertEqual(self._eng().decide(w)[0], {"action": "VERIFY_GATE"})

    def test_waiting_at_terminal_delivers(self):
        # 被动等待停在终点且满足交付条件 → 立即交付，绝不空等
        gm = GameMap(LIN2)
        w = world(LIN2, gm, "S15", state="WAITING", verified=True, good=97, freshness=72.0)
        self.assertEqual(self._eng().decide(w)[0], {"action": "DELIVER"})

    def test_moving_never_returns_empty(self):
        # 移动中任何情况都要产出推进动作，绝不空动作空等
        gm = GameMap(LIN2)
        w = world(LIN2, gm, "S01", state="MOVING")
        w.me.next_node_id = "SB"
        acts = self._eng().decide(w)
        self.assertTrue(acts and acts[0].get("action") in ("MOVE", "USE_RESOURCE"))


# P4：RUSH 前置路由。SA 处可绕路 ST 做任务；后期(≥RUSH_PREPOSITION_ROUND)未验核时直奔宫门，不再绕路。
# 真机归因：RUSH r450 触发时离 S14 远 → 验核 r492（42 帧空隙）→ 用时分损失 + 任务预算被吃。
PREMAP = _map(
    [_node("S01", "START", start=True), _node("SA"), _node("ST"), _node("S14", "GATE"),
     _node("S15", "FINISH", terminal=True)],
    [_edge("S01", "SA", 5), _edge("SA", "S14", 10), _edge("SA", "ST", 8),
     _edge("ST", "S14", 8), _edge("S14", "S15", 10)],
    {"startNodeId": "S01", "gateNodeId": "S14", "terminalNodeIds": ["S15"]},
)


class TestRushPreposition(unittest.TestCase):
    def _task_at_st(self):
        return [{"taskId": "TK", "taskTemplateId": "T01", "nodeId": "ST", "processRound": 3,
                 "active": True, "completed": False}]

    def test_detour_to_task_in_early_phase(self):
        # 早期(round=20)：未到 RUSH 前置窗口，仍按绕路做任务 → 去旁路 ST
        gm = GameMap(PREMAP)
        eng = DecisionEngine(GameContext(PID, "RED", 0, PREMAP))
        eng._stay_node = "SA"
        eng._processed_here = True
        w = world(PREMAP, gm, "SA", rnd=20, tasks=self._task_at_st(), nodes=[{"nodeId": "SA"}])
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "MOVE", "targetNodeId": "ST"})

    def test_no_detour_preposition_to_gate_in_late_phase(self):
        # 后期(round=400)未验核：P4 触发，直奔宫门 S14，不再绕路做任务
        gm = GameMap(PREMAP)
        eng = DecisionEngine(GameContext(PID, "RED", 0, PREMAP))
        eng._stay_node = "SA"
        eng._processed_here = True
        w = world(PREMAP, gm, "SA", rnd=400, tasks=self._task_at_st(), nodes=[{"nodeId": "SA"}])
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "MOVE", "targetNodeId": "S14"})

    def test_verified_routes_to_terminal_in_late_phase(self):
        # 已验核则不前置宫门，仍奔终点（P4 仅对未验核生效）
        gm = GameMap(PREMAP)
        eng = DecisionEngine(GameContext(PID, "RED", 0, PREMAP))
        eng._stay_node = "S14"
        eng._processed_here = True
        w = world(PREMAP, gm, "S14", rnd=400, verified=True, nodes=[{"nodeId": "S14"}])
        a = eng.decide(w)[0]
        self.assertEqual(a, {"action": "MOVE", "targetNodeId": "S15"})


if __name__ == "__main__":
    unittest.main()
