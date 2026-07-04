"""卡死复现单测（Iteration 8 失败模式）：MOVING 发空动作 → park WAITING + 0 进度；续行则前进。"""

import unittest

import _pathsetup  # noqa: F401
import sim_test_utils as u


class StuckTest(unittest.TestCase):
    def test_empty_action_while_moving_parks_waiting(self):
        """路线边 MOVING 发空动作 → 状态变 WAITING、位置与进度不变（Iter8 卡死根因）。"""
        eng = u.fresh_engine()
        red = eng.players["RED"]
        eng.step({"RED": [u.move_to("S02")], "BLUE": []})  # IDLE→MOVING，advance-on-start
        self.assertEqual(red.state, "MOVING")
        accum_before = red.move_accum
        pos_before = red.pos
        # 发空动作（旧客户端 bug：MOVING 只发 []）
        eng.step({"RED": [], "BLUE": []})
        self.assertEqual(red.state, "WAITING")
        self.assertEqual(red.pos, pos_before)
        self.assertEqual(red.move_accum, accum_before)  # 0 进度

    def test_keep_moving_advances(self):
        """MOVING 每帧重发 MOVE 到当前目标 → 持续前进，最终到达（Iter8 修复行为）。"""
        eng = u.fresh_engine()
        red = eng.players["RED"]
        frames = 0
        while red.pos == "S01" and frames < 200:
            eng.step({"RED": [u.move_to("S02")], "BLUE": []})
            frames += 1
        self.assertEqual(red.pos, "S02")
        self.assertEqual(red.state, "IDLE")

    def test_waiting_resumes_on_move(self):
        """WAITING 后发 MOVE 到当前目标 → 恢复 MOVING 并前进。"""
        eng = u.fresh_engine()
        red = eng.players["RED"]
        eng.step({"RED": [u.move_to("S02")], "BLUE": []})  # MOVING
        eng.step({"RED": [], "BLUE": []})  # → WAITING
        self.assertEqual(red.state, "WAITING")
        accum_before = red.move_accum
        eng.step({"RED": [u.move_to("S02")], "BLUE": []})  # 续行
        self.assertEqual(red.state, "MOVING")
        self.assertGreater(red.move_accum, accum_before)


if __name__ == "__main__":
    unittest.main()
