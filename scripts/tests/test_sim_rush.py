"""RUSH 触发 + 验核单测（§6.5）：四条件 / 450 强制 / 触发前 VERIFY_GATE 被拒。"""

import unittest

import _pathsetup  # noqa: F401
from protocol.enums import Phase
import sim_test_utils as u


class RushTest(unittest.TestCase):
    def test_no_rush_before_390(self):
        """390 帧前不触发 RUSH（即使玩家在 S14）。"""
        eng = u.fresh_engine()
        # 快进到 389 帧（玩家原地空等）
        for _ in range(389):
            eng.step({"RED": [], "BLUE": []})
        self.assertEqual(eng.phase, Phase.NORMAL)
        # 白盒把玩家放到 S14，第 390 帧前仍不触发
        eng.players["RED"].pos = "S14"
        eng.step({"RED": [], "BLUE": []})  # 第 390 帧
        self.assertEqual(eng.round, 390)
        # 390-449 窗口内"已到 S14"应触发
        self.assertEqual(eng.phase, Phase.RUSH)

    def test_rush_forced_at_450(self):
        """450 帧强制触发 RUSH。"""
        eng = u.fresh_engine()
        for _ in range(449):
            eng.step({"RED": [], "BLUE": []})
        self.assertEqual(eng.phase, Phase.NORMAL)
        eng.step({"RED": [], "BLUE": []})  # 第 450 帧
        self.assertEqual(eng.round, 450)
        self.assertEqual(eng.phase, Phase.RUSH)

    def test_verify_gate_rejected_before_rush(self):
        """RUSH 触发前提交 VERIFY_GATE 被拒（宫门未开放）。"""
        eng = u.fresh_engine()
        red = eng.players["RED"]
        red.pos = "S14"  # 在宫门
        eng.step({"RED": [{"action": "VERIFY_GATE"}], "BLUE": []})
        # 第 1 帧，phase=NORMAL → 拒绝
        ar = [r for r in eng.action_results if r["playerId"] == red.player_id]
        self.assertTrue(any(r["accepted"] is False for r in ar))

    def test_verify_gate_accepted_in_rush(self):
        """RUSH 阶段在 S14 提交 VERIFY_GATE 被接受，进入 VERIFYING。"""
        eng = u.fresh_engine()
        red = eng.players["RED"]
        # 快进到 RUSH
        for _ in range(450):
            eng.step({"RED": [], "BLUE": []})
        self.assertEqual(eng.phase, Phase.RUSH)
        red.pos = "S14"
        eng.step({"RED": [{"action": "VERIFY_GATE"}], "BLUE": []})
        self.assertEqual(red.state, "VERIFYING")
        ar = [r for r in eng.action_results if r["playerId"] == red.player_id]
        self.assertTrue(all(r["accepted"] for r in ar))


if __name__ == "__main__":
    unittest.main()
