"""P2 §5.2 悬赏机会主义单测：顺路/近路低代价破对手卡拿破关悬赏。

覆盖：相邻破卡、近路靠近、高防守/自方卡/远绕路/零收益/已完成的跳过、CONSERVATIVE 与 RUSH 不追。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from strategy.projection import RiskMode  # noqa: E402
from strategy.tuning import tuning_for_mode  # noqa: E402

PID = 1001


def _node(nid, typ="STATION", start=False, terminal=False):
    return {"nodeId": nid, "type": typ, "x": 0, "y": 0, "start": start, "terminal": terminal}


def _edge(a, b, dist=10):
    return {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": dist, "bidirectional": True}


def _map(nodes, edges):
    return {"matchId": "b", "durationRound": 600, "nodes": nodes, "edges": edges,
            "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
            "processNodes": []}


# 相邻场景：S01 直连悬赏卡 BG（BG→SJ→S15）；另有清路 S01→SA→SJ→S15。
def _adj_map(bg_dist=10):
    return _map(
        [_node("S01", "START", start=True), _node("BG"), _node("SA"),
         _node("SJ"), _node("S15", "FINISH", terminal=True)],
        [_edge("S01", "BG", bg_dist), _edge("BG", "SJ"), _edge("S01", "SA"),
         _edge("SA", "SJ"), _edge("SJ", "S15")])


# 近路场景：S01→M→BG（BG 非直连），BG→SJ→S15；清路 S01→SA→SJ→S15。
def _approach_map():
    return _map(
        [_node("S01", "START", start=True), _node("M"), _node("BG"), _node("SA"),
         _node("SJ"), _node("S15", "FINISH", terminal=True)],
        [_edge("S01", "M"), _edge("M", "BG"), _edge("BG", "SJ"),
         _edge("S01", "SA"), _edge("SA", "SJ"), _edge("SJ", "S15")])


def _world(sd, gm, defense=2, reward=30, owner="BLUE", node="S01",
           good=100, bad=0, fresh=100.0, phase="NORMAL", completed=False, winner=0):
    nodes = []
    if defense > 0 and owner:
        nodes.append({"nodeId": "BG", "guard": {"active": True, "defense": defense,
                                                 "ownerTeamId": owner}})
    bounty = {"bountyId": "B1", "nodeId": "BG", "rewardScore": reward,
              "active": not completed, "completed": completed, "winnerPlayerId": winner}
    inquire = {
        "round": 30, "phase": phase,
        "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE", "currentNodeId": node,
                     "verified": False, "goodFruit": good, "badFruit": bad, "freshness": fresh}],
        "nodes": nodes, "tasks": [], "contests": [], "bounties": [bounty], "events": [],
    }
    return WorldState(inquire, PID, gm)


def _setup(sd, w):
    gm = GameMap(sd)
    eng = DecisionEngine(GameContext(PID, "RED", 0, sd))
    eng.decide(w)  # 填充 projection_bus + tuning(EVEN)
    return eng, gm


def _bounty(eng, gm, w):
    return eng._maybe_bounty(w, w.me, gm, w.me.current_node_id, gm.terminal_nodes[0])


class TestBountyOpportunism(unittest.TestCase):
    def test_adjacent_bounty_breaks_guard(self):
        sd = _adj_map()
        w = _world(sd, GameMap(sd))
        eng, gm = _setup(sd, w)
        self.assertEqual(_bounty(eng, gm, w),
                         [{"action": "BREAK_GUARD", "targetNodeId": "BG",
                           "goodFruit": 1, "badFruit": 0}])

    def test_break_bounty_is_the_decided_action(self):
        # 端到端：整条决策管线也应输出破卡（EVEN 默认、无其它更优先动作）。
        sd = _adj_map()
        w = _world(sd, GameMap(sd))
        eng, gm = _setup(sd, w)
        acts = eng.decide(w)
        self.assertEqual(acts[0].get("action"), "BREAK_GUARD")
        self.assertEqual(acts[0].get("targetNodeId"), "BG")

    def test_approaches_nearby_bounty(self):
        sd = _approach_map()
        w = _world(sd, GameMap(sd))
        eng, gm = _setup(sd, w)
        self.assertEqual(_bounty(eng, gm, w), [{"action": "MOVE", "targetNodeId": "M"}])

    def test_skips_high_defense_bounty(self):
        # 防守值 20：低成本(最多好2坏2=10)破不了 → _plan_attack=None → 放弃。
        sd = _adj_map()
        w = _world(sd, GameMap(sd), defense=20)
        eng, gm = _setup(sd, w)
        self.assertIsNone(_bounty(eng, gm, w))

    def test_skips_own_team_guard(self):
        # 悬赏卡是本方设的：破它不给本方悬赏 → 跳过。
        sd = _adj_map()
        w = _world(sd, GameMap(sd), owner="RED")
        eng, gm = _setup(sd, w)
        self.assertIsNone(_bounty(eng, gm, w))

    def test_skips_far_bounty_beyond_max_extra(self):
        # 悬赏卡远（额外帧 > BOUNTY_MAX_EXTRA_FRAMES=25）→ 不大幅改道。
        sd = _adj_map(bg_dist=30)
        w = _world(sd, GameMap(sd))
        eng, gm = _setup(sd, w)
        self.assertIsNone(_bounty(eng, gm, w))

    def test_skips_zero_reward_via_delta_floor(self):
        # 悬赏得分 0：ΔEV = -破卡代价 < BOUNTY_MIN_NET_SCORE → 分数地板拒绝。
        sd = _adj_map()
        w = _world(sd, GameMap(sd), reward=0)
        eng, gm = _setup(sd, w)
        self.assertIsNone(_bounty(eng, gm, w))

    def test_skips_completed_bounty(self):
        sd = _adj_map()
        w = _world(sd, GameMap(sd), completed=True, winner=2002)
        eng, gm = _setup(sd, w)
        self.assertIsNone(_bounty(eng, gm, w))

    def test_conservative_does_not_chase_bounty(self):
        # 领先锁胜：不为悬赏花好果/时间。
        sd = _adj_map()
        w = _world(sd, GameMap(sd))
        eng, gm = _setup(sd, w)
        eng.tuning = tuning_for_mode(RiskMode.CONSERVATIVE)
        self.assertIsNone(_bounty(eng, gm, w))

    def test_rush_does_not_chase_bounty(self):
        # RUSH 保交付优先，不追悬赏。
        sd = _adj_map()
        w = _world(sd, GameMap(sd), phase="RUSH")
        eng, gm = _setup(sd, w)
        self.assertIsNone(_bounty(eng, gm, w))


if __name__ == "__main__":
    unittest.main()
