"""metrics 单测：用夹具日志验证指标计算。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from analysis.parser import parse_file  # noqa: E402
from analysis import metrics as M  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures_match_mock.log")


class TestMetricsFixture(unittest.TestCase):
    def setUp(self):
        self.trace = parse_file(FIXTURE)[-1]
        self.m = M.compute(self.trace)

    def test_delivery(self):
        self.assertTrue(self.m.delivered)
        self.assertEqual(self.m.deliver_round, 81)
        self.assertAlmostEqual(self.m.fresh_at_deliver, 95.95, places=2)
        self.assertEqual(self.m.good_fruit_at_deliver, 99)
        self.assertEqual(self.m.task_score, 90)
        self.assertTrue(self.m.i_won)

    def test_freshness_trajectory(self):
        self.assertGreater(len(self.m.fresh_traj), 50)
        # 鲜度从 100 单调下降到 ~96
        first_fresh = self.m.fresh_traj[0][1]
        last_fresh = self.m.fresh_traj[-1][1]
        self.assertAlmostEqual(first_fresh, 100.0, places=1)
        self.assertLess(last_fresh, 97)
        # 交付鲜度未跌破 90 → 无好果转坏阈值跨越
        self.assertEqual(self.m.good_fruit_loss_conversion, 0)

    def test_good_fruit_attribution(self):
        # 100 → 99：损失 1 篒。种卡 SET_GUARD extra_good=1 是主要消耗
        self.assertEqual(self.m.good_fruit_loss_total, 1)
        self.assertGreaterEqual(self.m.good_fruit_loss_spend, 1)
        self.assertEqual(self.m.good_fruit_loss_conversion, 0)

    def test_no_stalls(self):
        # 修复后不应有卡死段
        self.assertEqual(self.m.stalls, [])

    def test_block_encounters(self):
        nodes = [e.node for e in self.m.encounters]
        self.assertIn("S13", nodes)
        s13 = next(e for e in self.m.encounters if e.node == "S13")
        self.assertEqual(s13.kind, "obstacle")
        self.assertIsNotNone(s13.end_round)  # 已解除

    def test_budget_trajectory(self):
        self.assertEqual(len(self.m.budget_traj), len(self.trace.frames))
        # 早期 est 较大（~441），逐步下降
        self.assertGreater(self.m.budget_traj[0][1], 400)
        self.assertLess(self.m.budget_traj[-1][1], 10)

    def test_offensive_guard(self):
        # S10 有一次 SET_GUARD 并增援
        self.assertTrue(any(g.node == "S10" for g in self.m.guards))
        g = next(g for g in self.m.guards if g.node == "S10")
        self.assertTrue(g.reinforced)
        self.assertEqual(g.cost_frames, 4)

    def test_rush_timing(self):
        self.assertIsNotNone(self.m.rush_start_round)
        self.assertGreater(self.m.rush_start_round, 60)
        self.assertLess(self.m.rush_start_round, 81)
        self.assertIsNotNone(self.m.verify_end_round)

    def test_histograms(self):
        self.assertIn("MOVE", self.m.action_hist)
        self.assertIn("NONE", self.m.action_hist)
        self.assertIsNotNone(self.m.none_heartbeat_ratio)
        # mock 无拒绝
        self.assertEqual(self.m.reject_hist, {})

    def test_windows_empty_in_mock(self):
        # mock 无窗口
        self.assertEqual(self.m.windows, [])

    def test_opponent(self):
        # mock 蓝方未交付
        self.assertFalse(self.m.opp_delivered)


class TestStallDetection(unittest.TestCase):
    """构造一个含卡死段的 trace 验证检测。"""

    def test_stall_segment_detected(self):
        from analysis.parser import Frame, Action, MatchTrace
        from analysis.metrics import compute
        frames = []
        actions = []
        # r1-2 正常 MOVE 前进（node 变化）
        frames.append(Frame(round=1, phase="NORMAL", node="S01", state="MOVING", fresh=99))
        actions.append(Action(round=1, action="MOVE", target="S02"))
        frames.append(Frame(round=2, phase="NORMAL", node="S02", state="IDLE", fresh=98))
        actions.append(Action(round=2, action="MOVE", target="S03"))
        # r3-7 卡死：MOVING + NONE + node 不变
        for r in range(3, 8):
            frames.append(Frame(round=r, phase="NORMAL", node="S02", state="MOVING", fresh=97))
            actions.append(Action(round=r, action="NONE"))
        # r8 恢复
        frames.append(Frame(round=8, phase="NORMAL", node="S03", state="IDLE", fresh=96))
        actions.append(Action(round=8, action="MOVE", target="S04"))
        t = MatchTrace(frames=frames, actions=actions)
        m = compute(t)
        self.assertEqual(len(m.stalls), 1)
        self.assertEqual(m.stalls[0].start_round, 3)
        self.assertEqual(m.stalls[0].end_round, 7)
        self.assertEqual(m.stalls[0].length, 5)
        self.assertEqual(m.stalls[0].node, "S02")

    def test_processing_not_stall(self):
        # PROCESSING + NONE 不是卡死
        from analysis.parser import Frame, Action, MatchTrace
        from analysis.metrics import compute
        frames = [Frame(round=r, phase="NORMAL", node="S02", state="PROCESSING", fresh=99)
                  for r in range(1, 8)]
        actions = [Action(round=r, action="NONE") for r in range(1, 8)]
        t = MatchTrace(frames=frames, actions=actions)
        m = compute(t)
        self.assertEqual(m.stalls, [])


if __name__ == "__main__":
    unittest.main()
