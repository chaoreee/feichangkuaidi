"""运行期对手类追踪器 OpponentTracker 单测（Iter 37 §1，纯观测）。

覆盖：设卡次数累积（新节点计数，己方设卡不计）、用冰次数（库存递减）、
鲜度 min/last、交付帧、分类与离线 opponent_classifier 一致（guard>quality>speed）、
首帧安全（无 prev 不崩）、无 opponent 安全。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_state import WorldState  # noqa: E402
from strategy.opponent_tracker import (  # noqa: E402
    OpponentTracker, CLASS_GUARD, CLASS_QUALITY, CLASS_SPEED, CLASS_UNKNOWN,
)

PID = 1001
OPP = 2002
ME_TEAM = "RED"
OPP_TEAM = "BLUE"


def _world(opp_fresh=None, opp_good=None, opp_ice=None, opp_delivered=False,
           opp_task=None, nodes=None, rnd=1):
    """构造最小 WorldState：me + opponent + 节点（含可选 guard）。"""
    players = [
        {"playerId": PID, "teamId": ME_TEAM, "freshness": 100, "goodFruit": 100,
         "currentNodeId": "S01", "state": "IDLE"},
        {"playerId": OPP, "teamId": OPP_TEAM,
         "freshness": opp_fresh if opp_fresh is not None else 100,
         "goodFruit": opp_good if opp_good is not None else 100,
         "delivered": opp_delivered,
         "taskScore": opp_task or 0,
         "resources": {"ICE_BOX": opp_ice} if opp_ice is not None else {},
         "currentNodeId": "S05", "state": "IDLE"},
    ]
    return WorldState({"matchId": "t", "round": rnd, "players": players,
                       "nodes": nodes or []}, PID)


def _guard_node(nid, owner):
    return {"nodeId": nid, "guard": {"active": True, "defense": 5, "ownerTeamId": owner}}


class TestOpponentTracker(unittest.TestCase):
    def test_first_frame_safe_no_count(self):
        # 首帧有对手设卡节点但不计数（无 prev 基线），class 仍按信号判
        w = _world(opp_fresh=90, opp_good=98, nodes=[_guard_node("S10", OPP_TEAM)])
        t = OpponentTracker()
        t.update(w)
        cls, sig = t.classify()
        self.assertEqual(sig["oppGuardCount"], 0)  # 首帧不计数
        # guard=0, fresh=90>=85, good=98>=95 → quality
        self.assertEqual(cls, CLASS_QUALITY)

    def test_guard_placements_counted_on_new_node(self):
        t = OpponentTracker()
        t.update(_world(nodes=[_guard_node("S10", OPP_TEAM)]))  # 首帧 S10，不计数
        t.update(_world(nodes=[_guard_node("S10", OPP_TEAM)]))  # 持续 S10，无新增
        t.update(_world(nodes=[_guard_node("S10", OPP_TEAM), _guard_node("S07", OPP_TEAM)]))  # +S07
        _, sig = t.classify()
        self.assertEqual(sig["oppGuardCount"], 1)  # 仅 S07 新增计数
        self.assertEqual(t.classify()[0], CLASS_GUARD)

    def test_my_guard_not_counted(self):
        t = OpponentTracker()
        t.update(_world(nodes=[_guard_node("S10", ME_TEAM)]))  # 己方设卡
        t.update(_world(nodes=[_guard_node("S10", ME_TEAM)]))
        _, sig = t.classify()
        self.assertEqual(sig["oppGuardCount"], 0)

    def test_ice_usage_counted_on_decrease(self):
        t = OpponentTracker()
        t.update(_world(opp_ice=3))
        t.update(_world(opp_ice=3))   # 不变
        t.update(_world(opp_ice=1))   # 用了 2
        t.update(_world(opp_ice=4))   # 领了 3（不计使用）
        t.update(_world(opp_ice=2))   # 用了 2
        _, sig = t.classify()
        self.assertEqual(sig["iceUsedCount"], 4)

    def test_freshness_min_and_last(self):
        t = OpponentTracker()
        for fr in (95.0, 88.0, 82.0, 90.0):
            t.update(_world(opp_fresh=fr))
        _, sig = t.classify()
        self.assertEqual(sig["freshnessMin"], 82.0)
        self.assertEqual(sig["freshnessEnd"], 90.0)  # last

    def test_deliver_frame_recorded(self):
        t = OpponentTracker()
        t.update(_world(opp_delivered=False, rnd=100))
        t.update(_world(opp_delivered=False, rnd=200))
        t.update(_world(opp_delivered=True, rnd=300))
        t.update(_world(opp_delivered=True, rnd=400))
        _, sig = t.classify()
        self.assertEqual(sig["oppDeliverFrame"], 300)  # 首次交付帧

    def test_classify_speed_when_low_fresh(self):
        t = OpponentTracker()
        t.update(_world(opp_fresh=70.0, opp_good=80))
        self.assertEqual(t.classify()[0], CLASS_SPEED)

    def test_classify_quality_with_ice_even_if_good_low(self):
        t = OpponentTracker()
        t.update(_world(opp_fresh=88.0, opp_good=80, opp_ice=2))
        t.update(_world(opp_fresh=88.0, opp_good=80, opp_ice=1))  # 用 1 冰
        cls, sig = t.classify()
        self.assertEqual(cls, CLASS_QUALITY)
        self.assertEqual(sig["iceUsedCount"], 1)

    def test_no_opponent_safe(self):
        # 无 opponent（玩家列表只有 me）
        w = WorldState({"matchId": "t", "round": 1,
                        "players": [{"playerId": PID, "teamId": ME_TEAM}],
                        "nodes": []}, PID)
        t = OpponentTracker()
        t.update(w)
        self.assertEqual(t.classify()[0], CLASS_UNKNOWN)

    def test_guard_overrides_quality(self):
        # 鲜度高且有好果 → quality，但一旦设卡 → guard（优先级）
        t = OpponentTracker()
        t.update(_world(opp_fresh=95, opp_good=99))  # quality 倾向
        self.assertEqual(t.classify()[0], CLASS_QUALITY)
        t.update(_world(opp_fresh=95, opp_good=99, nodes=[_guard_node("S10", OPP_TEAM)]))
        t.update(_world(opp_fresh=95, opp_good=99, nodes=[_guard_node("S10", OPP_TEAM)]))
        self.assertEqual(t.classify()[0], CLASS_GUARD)


if __name__ == "__main__":
    unittest.main()
