"""Layer 2 档位参数映射 tuning_for_mode 单测（§5.1 / §9）。

覆盖：三档参数映射正确、EVEN 严格等于 config 既有默认、ΔEV 阈值三档均非负。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from strategy.projection import RiskMode  # noqa: E402
from strategy.tuning import tuning_for_mode  # noqa: E402


class TestTuningForMode(unittest.TestCase):
    def test_even_equals_existing_defaults(self):
        t = tuning_for_mode(RiskMode.EVEN)
        self.assertEqual(t.task_seek_target, config.TASK_SEEK_TARGET)
        self.assertEqual(t.task_detour_max_extra_frames, config.TASK_DETOUR_MAX_EXTRA_FRAMES)
        self.assertEqual(t.action_min_net_score, config.ACTION_MIN_NET_SCORE)

    def test_conservative_no_detour_higher_floor(self):
        t = tuning_for_mode(RiskMode.CONSERVATIVE)
        self.assertEqual(t.task_seek_target, 0)
        self.assertEqual(t.task_detour_max_extra_frames, 0)
        self.assertGreater(t.action_min_net_score, config.ACTION_MIN_NET_SCORE)

    def test_aggressive_higher_target_capped_detour(self):
        t = tuning_for_mode(RiskMode.AGGRESSIVE)
        self.assertEqual(t.task_seek_target, config.AGGRESSIVE_TASK_SEEK_TARGET)
        self.assertGreaterEqual(t.task_seek_target, config.TASK_SEEK_TARGET)
        self.assertEqual(t.task_detour_max_extra_frames,
                         config.AGGRESSIVE_TASK_DETOUR_MAX_EXTRA_FRAMES)
        # AGGRESSIVE 绕路上限刻意从直觉 120 收敛到 90（§5.1）。
        self.assertEqual(t.task_detour_max_extra_frames, 90)

    def test_all_modes_have_nonnegative_floor(self):
        # 铁律：任何档位 ΔEV 阈值都不得为负（更进取只放宽下限，不允许净负分）。
        for mode in (RiskMode.CONSERVATIVE, RiskMode.EVEN, RiskMode.AGGRESSIVE):
            self.assertGreaterEqual(tuning_for_mode(mode).action_min_net_score, 0)

    def test_rush_protect_threshold_per_mode(self):
        # §5.1 行4：CONSERVATIVE/EVEN 沿用既有 90；AGGRESSIVE 更克制（仅危急才用护果令）。
        self.assertEqual(tuning_for_mode(RiskMode.CONSERVATIVE).rush_protect_freshness_below,
                         config.RUSH_PROTECT_FRESHNESS_BELOW)
        self.assertEqual(tuning_for_mode(RiskMode.EVEN).rush_protect_freshness_below,
                         config.RUSH_PROTECT_FRESHNESS_BELOW)
        self.assertEqual(tuning_for_mode(RiskMode.AGGRESSIVE).rush_protect_freshness_below,
                         config.AGGRESSIVE_RUSH_PROTECT_FRESHNESS_BELOW)
        self.assertLess(tuning_for_mode(RiskMode.AGGRESSIVE).rush_protect_freshness_below,
                        tuning_for_mode(RiskMode.EVEN).rush_protect_freshness_below)

    def test_unknown_mode_falls_back_to_even(self):
        self.assertEqual(tuning_for_mode("WHATEVER").mode, RiskMode.EVEN)


if __name__ == "__main__":
    unittest.main()
