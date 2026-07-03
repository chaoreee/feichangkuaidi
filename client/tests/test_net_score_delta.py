"""分数质量地板 net_score_delta 单测（§3.3, P1.5）。

覆盖：正 ΔEV（追任务分跨里程碑）、负 ΔEV（为一点分烧好果/纯耗时）、
与 core/rules.py 的估分一致性、AGGRESSIVE 放宽阈值仍不许净负分通过的语义。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rules  # noqa: E402
from strategy.projection import project_final_score, net_score_delta  # noqa: E402


class TestProjectFinalScore(unittest.TestCase):
    def test_delivered_matches_rules_composition(self):
        deliver, base, good, fresh = 460, 60, 90, 85.0
        expected = rules.total_score([
            rules.delivery_base_score(base),
            rules.good_fruit_score(good),
            rules.freshness_score(fresh),
            rules.time_score(deliver, base),
            rules.task_score(base, delivered=True),
            rules.bounty_score(0, delivered=True),
        ], 0)
        self.assertEqual(project_final_score(deliver, base, good, fresh), float(expected))

    def test_not_delivered_uses_undelivered_scoring(self):
        # deliver_frame 超过 duration → 未交付口径：无送达/好果/鲜度/用时分。
        score = project_final_score(700, 100, 100, 100.0, raw_bounty=30, duration=600)
        expected = rules.total_score([
            rules.task_score(100, delivered=False),
            rules.bounty_score(30, delivered=False),
        ], 0)
        self.assertEqual(score, float(expected))

    def test_none_deliver_frame_is_undelivered(self):
        self.assertEqual(project_final_score(None, 60, 90, 85.0),
                         float(rules.total_score([rules.task_score(60, False),
                                                  rules.bounty_score(0, False)], 0)))


class TestNetScoreDelta(unittest.TestCase):
    BASE = dict(deliver_frame=460, task_base=60, good_fruit=90, freshness=85.0)

    def test_task_milestone_gain_is_positive(self):
        # 60→90 跨里程碑（+35 里程碑，且用时分 min(base,90)/90 拉满），即使多花 10 帧仍应为正。
        delta = net_score_delta(extra_task_score=30, extra_frames=10, **self.BASE)
        self.assertGreater(delta, 0)

    def test_burning_good_fruit_for_tiny_task_is_negative(self):
        # 为 +1 任务分烧掉 10 好果 → 好果数量分大跌，净负（正是 839cfc9 的败局模式）。
        delta = net_score_delta(extra_task_score=1, good_fruit_burned=10, **self.BASE)
        self.assertLess(delta, 0)

    def test_pure_time_cost_no_gain_is_non_positive(self):
        # 纯额外耗时、无任何收益 → ΔEV ≤ 0（推迟交付只降用时分）。
        delta = net_score_delta(extra_frames=15, **self.BASE)
        self.assertLessEqual(delta, 0)

    def test_zero_action_is_zero_delta(self):
        self.assertEqual(net_score_delta(**self.BASE), 0.0)

    def test_freshness_loss_crossing_threshold_burns_good_fruit(self):
        # 鲜度从 85 掉到 78 跨过 80 阈值 → 触发 1 篓转坏，纯损耗应为负。
        delta = net_score_delta(extra_freshness_loss=7.0,
                                deliver_frame=460, task_base=60, good_fruit=90, freshness=85.0)
        self.assertLess(delta, 0)

    def test_bounty_gain_positive(self):
        delta = net_score_delta(extra_bounty=40, extra_frames=5, **self.BASE)
        self.assertGreater(delta, 0)

    def test_negative_delta_rejected_by_any_nonneg_threshold(self):
        # 语义校验：净负分动作在 EVEN(0) 与 AGGRESSIVE(0) 阈值下都应被拒。
        delta = net_score_delta(extra_task_score=1, good_fruit_burned=10, **self.BASE)
        self.assertFalse(delta >= 0)      # EVEN / AGGRESSIVE 阈值 0
        self.assertFalse(delta >= 8)      # CONSERVATIVE 阈值 8


if __name__ == "__main__":
    unittest.main()
