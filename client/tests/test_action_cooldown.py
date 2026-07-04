"""MOVING_ACTION_FORBIDDEN 重试风暴修复单测（Iter 33）。

真实 trace（3 局未交付根因）：到达对手设卡关隘 S10 后进入 WAITING 态，_keep_moving 回落 _plan
连发非 MOVE 节点动作，全被 MOVING_ACTION_FORBIDDEN 拒、连发成风暴烧光交付窗口——
  032341: BREAK_GUARD x52 + USE_RESOURCE(ICE_BOX) x287
  035502: BREAK_GUARD x54 + USE_RESOURCE(ICE_BOX) x201
  034523: FORCED_PASS x60 + RUSH_PROTECT x180
修复：_apply_rejection_feedback 对非 MOVE 动作 + MOVING_ACTION_FORBIDDEN 按签名冷却；
_freshness_rescue / _maybe_rush_protect / _maybe_bounty / _breakthrough 检查 _action_cooled，
冷却中跳过 → _plan 落到 _advance(MOVE) 重路由绕行。DELIVER/VERIFY_GATE 不受影响（不被该码拒）。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from protocol import actions  # noqa: E402
from protocol.enums import Action, ResourceType  # noqa: E402
from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402

PID = 1001
TEAM = "RED"
OPP = "BLUE"

# S01(起点) - S10(关隘，可被对手设卡) - S15(终点)；S10-S13-S15 绕行备路。
SD = {
    "matchId": "t", "durationRound": 600,
    "nodes": [
        {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "S10", "type": "KEY_PASS", "x": 1, "y": 0},
        {"nodeId": "S13", "type": "STATION", "x": 2, "y": 1},
        {"nodeId": "S15", "type": "FINISH", "x": 3, "y": 0, "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S10", "routeType": "ROAD",
         "distance": 10, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "S10", "toNodeId": "S15", "routeType": "ROAD",
         "distance": 10, "bidirectional": True},
        {"edgeId": "E3", "fromNodeId": "S10", "toNodeId": "S13", "routeType": "ROAD",
         "distance": 12, "bidirectional": True},
        {"edgeId": "E4", "fromNodeId": "S13", "toNodeId": "S15", "routeType": "ROAD",
         "distance": 12, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "S01",
                                   "terminalNodeIds": ["S15"], "safeZoneNodeIds": ["S15"]}}},
    "processNodes": [],
}


def _world(rnd, state="WAITING", node="S10", freshness=50.0, good=100,
           resources=None, verified=True, guard_owner=OPP, action_results=None,
           is_rush=False, phase="NORMAL"):
    """me 在 S10、WAITING、鲜度低于冰鉴阈值、持冰鉴的世界。"""
    nodes = []
    if guard_owner:
        nodes.append({"nodeId": "S10", "guard": {"active": True, "defense": 3,
                                                 "ownerTeamId": guard_owner}})
    inq = {
        "round": rnd, "phase": "RUSH" if is_rush else phase,
        "players": [{"playerId": PID, "teamId": TEAM, "state": state,
                     "currentNodeId": node, "nextNodeId": None,
                     "verified": verified, "goodFruit": good, "badFruit": 0,
                     "freshness": freshness, "resources": resources or {}}],
        "nodes": nodes,
        "actionResults": action_results or [],
    }
    return WorldState(inq, PID)


def _engine():
    return DecisionEngine(GameContext(PID, TEAM, 0, SD))


def _main(result):
    if not result:
        return None, None
    a = result[0]
    return a.get("action"), a.get("targetNodeId")


class TestActionCooldown(unittest.TestCase):
    def test_moving_forbidden_sets_action_cooldown(self):
        """USE_RESOURCE(ICE_BOX) 被 MOVING_ACTION_FORBIDDEN 拒 → 按签名冷却。"""
        rnd = 200
        eng = _engine()
        eng._last_main_action = {"action": Action.USE_RESOURCE, "resourceType": ResourceType.ICE_BOX}
        ar = [{"playerId": PID, "round": rnd - 1, "accepted": False,
               "errorCode": "MOVING_ACTION_FORBIDDEN"}]
        w = _world(rnd, action_results=ar)
        eng._apply_rejection_feedback(w)
        sig = (Action.USE_RESOURCE, None, ResourceType.ICE_BOX)
        self.assertEqual(eng._action_cooldown.get(sig),
                         rnd + config.REJECT_ACTION_COOLDOWN_ROUNDS)

    def test_move_rejection_not_cooled_as_action(self):
        """MOVE 被拒仍走节点拉黑（_cooldown），不进 _action_cooldown。"""
        rnd = 200
        eng = _engine()
        eng._last_main_action = {"action": Action.MOVE, "targetNodeId": "S10"}
        ar = [{"playerId": PID, "round": rnd - 1, "accepted": False,
               "errorCode": "MOVE_BLOCKED_BY_GUARD"}]
        w = _world(rnd, action_results=ar)
        eng._apply_rejection_feedback(w)
        self.assertEqual(eng._cooldown.get("S10"), rnd + config.REJECT_BLOCK_ROUNDS)
        self.assertFalse(eng._action_cooldown)

    def test_icebox_storm_breaks_to_reroute(self):
        """WAITING 态冰鉴被 MOVING_ACTION_FORBIDDEN 拒后：冷却中 _freshness_rescue 跳过，
        _plan 落到 _advance → MOVE 重路由（不再连发 ICE_BOX 烧光交付窗口）。"""
        rnd = 200
        eng = _engine()
        # 上一帧 ICE_BOX 被拒 → 设冷却
        eng._last_main_action = {"action": Action.USE_RESOURCE, "resourceType": ResourceType.ICE_BOX}
        ar = [{"playerId": PID, "round": rnd - 1, "accepted": False,
               "errorCode": "MOVING_ACTION_FORBIDDEN"}]
        w = _world(rnd, freshness=50.0, resources={"ICE_BOX": 1}, action_results=ar)
        eng._update_projection(w)
        eng._apply_rejection_feedback(w)
        result = eng.decide(w)
        act, tgt = _main(result)
        self.assertEqual(act, "MOVE", f"冰鉴冷却中应重路由 MOVE，实得：{result}")
        self.assertIn(tgt, ("S15", "S13"))

    def test_icebox_resumes_after_cooldown_expires(self):
        """冷却过期后 _freshness_rescue 恢复发冰鉴（防回归：冷却不是永久禁用）。"""
        rnd = 200
        eng = _engine()
        # 设一个已过期的冷却
        sig = (Action.USE_RESOURCE, None, ResourceType.ICE_BOX)
        eng._action_cooldown[sig] = rnd - 1  # 已过期
        w = _world(rnd, freshness=50.0, resources={"ICE_BOX": 1})
        act = eng._freshness_rescue(w, w.me)
        self.assertIsNotNone(act, "冷却过期后应恢复冰鉴")
        self.assertEqual(act.get("action"), Action.USE_RESOURCE)

    def test_rush_protect_skipped_when_cooled(self):
        """RUSH_PROTECT 被 MOVING_ACTION_FORBIDDEN 拒后冷却中跳过。"""
        rnd = 400
        eng = _engine()
        sig = (Action.RUSH_PROTECT, None, None)
        eng._action_cooldown[sig] = rnd + config.REJECT_ACTION_COOLDOWN_ROUNDS
        w = _world(rnd, is_rush=True, freshness=10.0)
        eng._update_projection(w)  # 初始化 tuning
        act = eng._maybe_rush_protect(w, w.me)
        self.assertIsNone(act, "RUSH_PROTECT 冷却中应跳过")
        # 过期恢复
        w2 = _world(rnd + config.REJECT_ACTION_COOLDOWN_ROUNDS + 1, is_rush=True, freshness=10.0)
        eng2 = _engine()
        eng2._update_projection(w2)
        act2 = eng2._maybe_rush_protect(w2, w2.me)
        self.assertIsNotNone(act2, "冷却过期应恢复 RUSH_PROTECT")

    def test_forced_pass_skipped_falls_to_alternative(self):
        """FORCED_PASS 被 MOVING_ACTION_FORBIDDEN 拒后冷却中：_breakthrough 不再发 FORCED_PASS，
        改发替代动作（BREAK_GUARD）或 MOVE——关键是不重发被拒的同一动作。"""
        rnd = 200
        eng = _engine()
        sig = (Action.FORCED_PASS, "S10", None)
        eng._action_cooldown[sig] = rnd + config.REJECT_ACTION_COOLDOWN_ROUNDS
        w = _world(rnd, freshness=50.0)
        eng._update_projection(w)
        out = eng._breakthrough(w, w.me, eng.ctx.game_map, "S10", "S15")
        act = out[0].get("action") if out else None
        self.assertNotEqual(act, Action.FORCED_PASS,
                            f"FORCED_PASS 冷却中不应重发，实得：{out}")

    def test_break_guard_skipped_falls_to_alternative(self):
        """BREAK_GUARD 被 MOVING_ACTION_FORBIDDEN 拒后冷却中：_breakthrough 不再发 BREAK_GUARD。"""
        rnd = 200
        eng = _engine()
        sig = (Action.BREAK_GUARD, "S10", None)
        eng._action_cooldown[sig] = rnd + config.REJECT_ACTION_COOLDOWN_ROUNDS
        w = _world(rnd, freshness=50.0)
        eng._update_projection(w)
        out = eng._breakthrough(w, w.me, eng.ctx.game_map, "S10", "S15")
        act = out[0].get("action") if out else None
        self.assertNotEqual(act, Action.BREAK_GUARD,
                            f"BREAK_GUARD 冷却中不应重发，实得：{out}")

    def test_all_breakthrough_cooled_falls_to_move(self):
        """所有突破动作（BREAK_GUARD + FORCED_PASS）均冷却中 → _breakthrough 回落 MOVE 重路由。"""
        rnd = 200
        eng = _engine()
        eng._action_cooldown[(Action.BREAK_GUARD, "S10", None)] = rnd + config.REJECT_ACTION_COOLDOWN_ROUNDS
        eng._action_cooldown[(Action.FORCED_PASS, "S10", None)] = rnd + config.REJECT_ACTION_COOLDOWN_ROUNDS
        w = _world(rnd, freshness=50.0)
        eng._update_projection(w)
        out = eng._breakthrough(w, w.me, eng.ctx.game_map, "S10", "S15")
        act = out[0].get("action") if out else None
        self.assertEqual(act, "MOVE", f"全突破动作冷却中应回落 MOVE，实得：{out}")

    def test_break_guard_skipped_in_bounty(self):
        """BREAK_GUARD 被 MOVING_ACTION_FORBIDDEN 拒后 _maybe_bounty 跳过该悬赏候选（不重发）。"""
        rnd = 200
        eng = _engine()
        bn = "S10"
        eng._action_cooldown[(Action.BREAK_GUARD, bn, None)] = rnd + config.REJECT_ACTION_COOLDOWN_ROUNDS
        # 玩家在 S01（与 S10 相邻），S10 有对手设卡 + 悬赏
        inq = {
            "round": rnd, "phase": "NORMAL",
            "players": [{"playerId": PID, "teamId": TEAM, "state": "IDLE",
                         "currentNodeId": "S01", "nextNodeId": None, "verified": True,
                         "goodFruit": 100, "badFruit": 0, "freshness": 80.0, "resources": {}}],
            "nodes": [{"nodeId": "S10", "guard": {"active": True, "defense": 3, "ownerTeamId": OPP}}],
            "bounties": [{"bountyId": "B1", "nodeId": bn, "rewardScore": 18,
                          "active": True, "completed": False, "winnerPlayerId": 0}],
            "actionResults": [],
        }
        w = WorldState(inq, PID)
        eng._update_projection(w)
        out = eng._maybe_bounty(w, w.me, eng.ctx.game_map, "S01", "S15")
        if out:
            self.assertNotEqual(out[0].get("action"), Action.BREAK_GUARD,
                                f"BREAK_GUARD 冷却中 _maybe_bounty 不应发出，实得：{out}")

    def test_deliver_while_waiting_not_blocked(self):
        """回归：WAITING 态在终点 DELIVER 不受 MOVING_ACTION_FORBIDDEN 冷却影响（不被该码拒）。"""
        rnd = 200
        eng = _engine()
        # 即便有某动作冷却，终点 DELIVER 仍应正常
        eng._action_cooldown[(Action.USE_RESOURCE, None, ResourceType.ICE_BOX)] = rnd + 99
        # 在终点 S15、已验核、有好果 → DELIVER（state=WAITING 也允许，Iter 8 行为）
        w = _world(rnd, state="WAITING", node="S15", freshness=50.0, good=100,
                   verified=True, guard_owner=None)
        result = eng.decide(w)
        act, _ = _main(result)
        self.assertEqual(act, "DELIVER", f"WAITING 在终点应 DELIVER，实得：{result}")


if __name__ == "__main__":
    unittest.main()
