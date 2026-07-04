"""P0（Iter 29）_keep_moving 在途目标失效校验单测。

covers：MOVING/WAITING 态重发 MOVE 前校验在途目标是否已被对手设卡 / 在冷却期——
失效则回落 _plan 全量重规划（_advance 绕行 / _breakthrough 突破），杜绝 vs2735 那种
MOVE_BLOCKED_BY_GUARD 连拒百帧、未交付的死锁。与 Iter 8（卡 S14）同源，补其盲区。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402

PID = 1001
TEAM = "RED"
OPP = "BLUE"


def _node(nid, typ="STATION", start=False, terminal=False):
    return {"nodeId": nid, "type": typ, "x": 0, "y": 0, "start": start, "terminal": terminal}


def _edge(a, b, dist=10):
    return {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": dist, "bidirectional": True}


# S01(起点) - SG(在途目标，可被设卡/冷却) - S15(终点)
#         └── SA(绕行备路) ─┘
# SG 直路更短(8+8=16)，SA 绕行(10+10=20)：SG 畅通时续行/最短路走 SG；SG 被设卡/冷却时
# _plan→_advance 绕行 SA（diff=4 < REROUTE_VS_CLEAR_EXTRA=20，不触发就地清障）。
SD = {"matchId": "km", "durationRound": 600,
      "nodes": [_node("S01", "START", start=True), _node("SG"), _node("SA"),
                _node("S15", "FINISH", terminal=True)],
      "edges": [_edge("S01", "SG", dist=8), _edge("SG", "S15", dist=8),
                _edge("S01", "SA", dist=10), _edge("SA", "S15", dist=10)],
      "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]}}},
      "processNodes": []}


def _world(guard_owner=None, cooldown_target=None, rnd=20, state="MOVING", next_node="SG"):
    """构造 me 在 S01、state=MOVING、在途目标 SG 的世界。

    guard_owner：在 SG 设 active 敌卡/己卡的归属队伍（None=无设卡）。
    cooldown_target：直接写入 eng._cooldown 的目标（模拟拒绝反馈拉黑）。
    """
    nodes = []
    if guard_owner:
        nodes.append({"nodeId": "SG", "guard": {"active": True, "defense": 3,
                                                "ownerTeamId": guard_owner}})
    inquire = {"round": rnd, "phase": "NORMAL",
               "players": [{"playerId": PID, "teamId": TEAM, "state": state,
                            "currentNodeId": "S01", "nextNodeId": next_node,
                            "verified": True, "goodFruit": 100, "badFruit": 0,
                            "freshness": 100.0}],
               "nodes": nodes}
    return WorldState(inquire, PID, None)


def _decide(guard_owner=None, cooldown_target=None, state="MOVING", next_node="SG", rnd=20):
    gm = GameMap(SD)
    eng = DecisionEngine(GameContext(PID, TEAM, 0, SD))
    if cooldown_target:
        eng._cooldown[cooldown_target] = rnd + 4  # 4 帧冷却未过期
    w = _world(guard_owner=guard_owner, cooldown_target=cooldown_target,
               state=state, next_node=next_node, rnd=rnd)
    return eng.decide(w)


def _main_action(result):
    """取首个非空动作的 (action, target)。"""
    if not result:
        return None, None
    a = result[0]
    return a.get("action"), a.get("targetNodeId")


class TestKeepMovingGuard(unittest.TestCase):
    def test_transit_target_guarded_replans(self):
        # SG 被对手设卡 → 不再续行 MOVE(SG)，回落 _plan → _advance 绕行 SA。
        act, tgt = _main_action(_decide(guard_owner=OPP))
        self.assertEqual((act, tgt), ("MOVE", "SA"),
                         f"在途目标被对手设卡应绕行 SA，实得：act={act} tgt={tgt}")

    def test_transit_target_cooldown_replans(self):
        # SG 在 _cooldown（拒绝反馈拉黑未过期）→ 同上回落 _plan → 绕行 SA。
        act, tgt = _main_action(_decide(cooldown_target="SG"))
        self.assertEqual((act, tgt), ("MOVE", "SA"),
                         f"在途目标在冷却期应绕行 SA，实得：act={act} tgt={tgt}")

    def test_transit_target_clear_continues(self):
        # SG 无设卡不在冷却 → 续行 MOVE(SG)（防回归）。
        act, tgt = _main_action(_decide())
        self.assertEqual((act, tgt), ("MOVE", "SG"))

    def test_transit_target_own_guard_continues(self):
        # SG 被己方设卡（owner==me.team_id）→ 己方卡不挡己方，仍 MOVE(SG)。
        act, tgt = _main_action(_decide(guard_owner=TEAM))
        self.assertEqual((act, tgt), ("MOVE", "SG"))

    def test_no_in_transit_target_replans(self):
        # nextNodeId=None + WAITING → 无在途目标，回落 _plan（重新规划前进，非空等）。
        act, tgt = _main_action(_decide(state="WAITING", next_node=None))
        self.assertEqual((act, tgt), ("MOVE", "SG"))


if __name__ == "__main__":
    unittest.main()
