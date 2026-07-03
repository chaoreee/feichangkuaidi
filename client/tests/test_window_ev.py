"""P2 §5.4 窗口 EV 单测。

覆盖：无代价牌优先级(兵争>验牒>免费强行)、献贡按档位门控(CONSERVATIVE 不烧/EVEN·AGGRESSIVE
好果下限不同)、低价值窗口不烧好果、鲜度<80 不可献贡、不为窗口烧马、无窗口返回 None。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_state import WorldState  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from strategy.projection import RiskMode  # noqa: E402
from strategy.tuning import tuning_for_mode  # noqa: E402

PID = 1001
SD = {"matchId": "w", "durationRound": 600,
      "nodes": [{"nodeId": "S02", "type": "STATION", "x": 0, "y": 0}],
      "edges": [], "map": {"gameplay": {"roles": {}}}, "processNodes": []}


def _world(contest_type="TASK", gp=0, token=0, permit=0, horse_buff=False,
           horse_res=0, good=100, fresh=100.0, contest=True):
    res = {}
    if token:
        res["PASS_TOKEN"] = token
    if permit:
        res["OFFICIAL_PERMIT"] = permit
    if horse_res:
        res["FAST_HORSE"] = horse_res
    buffs = [{"type": "FAST_HORSE", "remainingRound": 5}] if horse_buff else []
    contests = ([{"contestId": "C1", "contestType": contest_type, "redPlayerId": PID,
                  "bluePlayerId": 2222, "resolved": False}] if contest else [])
    inquire = {"round": 100, "phase": "NORMAL",
               "players": [{"playerId": PID, "teamId": "RED", "state": "CONTESTING",
                            "currentNodeId": "S02", "guardActionPoint": gp,
                            "goodFruit": good, "freshness": fresh,
                            "resources": res, "buffs": buffs}],
               "contests": contests}
    return WorldState(inquire, PID, None)


def _card(mode, **kw):
    eng = DecisionEngine(GameContext(PID, "RED", 0, SD))
    eng.tuning = tuning_for_mode(mode)
    w = _world(**kw)
    a = eng._window_card(w, w.me)
    return a.get("card") if a else None


class TestFreeCards(unittest.TestCase):
    def test_no_contest_returns_none(self):
        self.assertIsNone(_card(RiskMode.EVEN, contest=False))

    def test_action_point_plays_bing_zheng(self):
        self.assertEqual(_card(RiskMode.EVEN, gp=4), "BING_ZHENG")

    def test_token_plays_yan_die(self):
        self.assertEqual(_card(RiskMode.EVEN, gp=0, token=1), "YAN_DIE")

    def test_permit_plays_yan_die(self):
        self.assertEqual(_card(RiskMode.EVEN, gp=0, permit=1), "YAN_DIE")

    def test_move_buff_plays_free_qiang_xing(self):
        self.assertEqual(_card(RiskMode.EVEN, gp=0, horse_buff=True), "QIANG_XING")

    def test_free_cards_played_even_when_conservative(self):
        # CONSERVATIVE 只出无代价牌——兵争仍出（行动点无交付代价）。
        self.assertEqual(_card(RiskMode.CONSERVATIVE, gp=4), "BING_ZHENG")

    def test_bing_zheng_preferred_over_token(self):
        self.assertEqual(_card(RiskMode.EVEN, gp=4, token=1), "BING_ZHENG")


class TestXianGongGating(unittest.TestCase):
    def test_conservative_never_burns_good_fruit(self):
        # 无无代价牌、只有好果+鲜度：CONSERVATIVE 锁胜 → 弃权，不献贡。
        self.assertEqual(_card(RiskMode.CONSERVATIVE, good=100, fresh=100.0), "ABSTAIN")

    def test_even_burns_for_valuable_contest_when_good_high(self):
        self.assertEqual(_card(RiskMode.EVEN, contest_type="TASK", good=100), "XIAN_GONG")

    def test_even_abstains_when_good_below_floor(self):
        # 好果 40 ≤ EVEN 下限 50 → 不烧。
        self.assertEqual(_card(RiskMode.EVEN, contest_type="TASK", good=40), "ABSTAIN")

    def test_even_abstains_for_low_value_contest(self):
        # RESOURCE 不在值得烧好果的窗口类型里 → 弃权。
        self.assertEqual(_card(RiskMode.EVEN, contest_type="RESOURCE", good=100), "ABSTAIN")

    def test_aggressive_lower_good_floor(self):
        # 好果 15 > AGGRESSIVE 下限 12 → 献贡；同样 15 在 EVEN(下限50) 则弃权。
        self.assertEqual(_card(RiskMode.AGGRESSIVE, contest_type="TASK", good=15), "XIAN_GONG")
        self.assertEqual(_card(RiskMode.EVEN, contest_type="TASK", good=15), "ABSTAIN")

    def test_low_freshness_cannot_xian_gong(self):
        # 鲜度 < 80 献贡成本不满足 → 弃权。
        self.assertEqual(_card(RiskMode.AGGRESSIVE, contest_type="TASK", good=100, fresh=70.0),
                         "ABSTAIN")

    def test_does_not_burn_horse_for_window(self):
        # 只有马资源（无 buff）、好果不足以献贡：不烧马强行 → 弃权（马留给交付提速）。
        self.assertEqual(_card(RiskMode.AGGRESSIVE, contest_type="TASK", good=0, horse_res=1),
                         "ABSTAIN")


if __name__ == "__main__":
    unittest.main()
