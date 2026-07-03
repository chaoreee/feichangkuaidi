"""风险档位状态机 ModeMachine 单测（§4.4）。

覆盖：gap 跨阈值 + 滞后后才切档、低置信回落 EVEN、band 内保持 EVEN、切档事件回报。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.projection import ModeMachine, RiskMode  # noqa: E402

LEAD = 40
HYST = 5
MIN_CONF = 0.55
HIGH_CONF = 0.8


class TestModeMachine(unittest.TestCase):
    def setUp(self):
        self.m = ModeMachine(LEAD, HYST, MIN_CONF)

    def test_starts_even(self):
        self.assertEqual(self.m.mode, RiskMode.EVEN)

    def test_switch_needs_hysteresis(self):
        # 前 HYST-1 帧不切；第 HYST 帧才切到 CONSERVATIVE。
        for _ in range(HYST - 1):
            mode, changed, _, _ = self.m.update(gap=100, confidence=HIGH_CONF)
            self.assertEqual(mode, RiskMode.EVEN)
            self.assertFalse(changed)
        mode, changed, from_mode, reason = self.m.update(gap=100, confidence=HIGH_CONF)
        self.assertEqual(mode, RiskMode.CONSERVATIVE)
        self.assertTrue(changed)
        self.assertEqual(from_mode, RiskMode.EVEN)
        self.assertEqual(reason, "gap_above_threshold")

    def test_aggressive_when_far_behind(self):
        for _ in range(HYST):
            mode, _, _, _ = self.m.update(gap=-100, confidence=HIGH_CONF)
        self.assertEqual(mode, RiskMode.AGGRESSIVE)

    def test_low_confidence_stays_even_despite_big_gap(self):
        for _ in range(HYST * 2):
            mode, changed, _, reason = self.m.update(gap=100, confidence=MIN_CONF - 0.01)
            self.assertEqual(mode, RiskMode.EVEN)
            self.assertFalse(changed)
        self.assertEqual(reason, "low_confidence")

    def test_within_band_stays_even(self):
        for _ in range(HYST * 2):
            mode, changed, _, _ = self.m.update(gap=LEAD - 1, confidence=HIGH_CONF)
        self.assertEqual(mode, RiskMode.EVEN)

    def test_interrupted_streak_resets(self):
        # 4 帧领先，中间插一帧 band 内 → 计数重置，需重新累积。
        for _ in range(HYST - 1):
            self.m.update(gap=100, confidence=HIGH_CONF)
        mode, changed, _, _ = self.m.update(gap=0, confidence=HIGH_CONF)  # 打断
        self.assertEqual(mode, RiskMode.EVEN)
        self.assertFalse(changed)
        for _ in range(HYST - 1):
            mode, changed, _, _ = self.m.update(gap=100, confidence=HIGH_CONF)
            self.assertFalse(changed)  # 计数已重置，尚未到 HYST
        mode, changed, _, _ = self.m.update(gap=100, confidence=HIGH_CONF)
        self.assertTrue(changed)
        self.assertEqual(mode, RiskMode.CONSERVATIVE)

    def test_switch_back_needs_hysteresis_again(self):
        for _ in range(HYST):
            self.m.update(gap=100, confidence=HIGH_CONF)
        self.assertEqual(self.m.mode, RiskMode.CONSERVATIVE)
        # 转向进取需再次累积 HYST 帧。
        for _ in range(HYST - 1):
            mode, changed, _, _ = self.m.update(gap=-100, confidence=HIGH_CONF)
            self.assertEqual(mode, RiskMode.CONSERVATIVE)
        mode, changed, from_mode, _ = self.m.update(gap=-100, confidence=HIGH_CONF)
        self.assertTrue(changed)
        self.assertEqual(mode, RiskMode.AGGRESSIVE)
        self.assertEqual(from_mode, RiskMode.CONSERVATIVE)


if __name__ == "__main__":
    unittest.main()
