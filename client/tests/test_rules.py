"""rules 规则公式单测，对齐任务书数值口径。"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rules  # noqa: E402


class TestMove(unittest.TestCase):
    def test_to_station_move_amount(self):
        self.assertEqual(rules.to_station_move_amount(30, "ROAD"), math.ceil(30 * 1380))
        self.assertEqual(rules.to_station_move_amount(44, "WATER"), math.ceil(44 * 1250))
        self.assertEqual(rules.to_station_move_amount(54, "MOUNTAIN"), math.ceil(54 * 1780))
        self.assertEqual(rules.to_station_move_amount(46, "BRANCH"), math.ceil(46 * 1550))

    def test_per_frame_move_amount(self):
        self.assertEqual(rules.per_frame_move_amount(1000, 1000), 1000)
        self.assertEqual(rules.per_frame_move_amount(1200, 1000), 1200)  # 快马
        self.assertEqual(rules.per_frame_move_amount(1000, 1350), 740)   # 暴雨水路
        self.assertEqual(rules.per_frame_move_amount(1000, 1100), 909)   # 山雾山路

    def test_weather_move_multiplier(self):
        self.assertEqual(rules.weather_move_multiplier("WATER", "HEAVY_RAIN"), 1350)
        self.assertEqual(rules.weather_move_multiplier("MOUNTAIN", "MOUNTAIN_FOG"), 1100)
        self.assertEqual(rules.weather_move_multiplier("ROAD", "HOT"), 1000)
        self.assertEqual(rules.weather_move_multiplier("WATER", "MOUNTAIN_FOG"), 1000)


class TestFreshness(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(rules.crossed_good_to_bad_thresholds(100, 89.9), [90])
        self.assertEqual(rules.crossed_good_to_bad_thresholds(90, 90), [])   # 等于不触发
        self.assertEqual(rules.crossed_good_to_bad_thresholds(95, 68), [90, 80, 70])
        self.assertEqual(rules.crossed_good_to_bad_thresholds(50, 50), [])

    def test_loss(self):
        self.assertAlmostEqual(rules.freshness_loss(0.055), 0.055)
        self.assertAlmostEqual(rules.freshness_loss(0.05, 1.5), 0.075)          # 酷暑
        self.assertAlmostEqual(rules.freshness_loss(0.05, 1.0, 0.2), 0.01)      # 护果令


class TestGuard(unittest.TestCase):
    def test_defense(self):
        self.assertEqual(rules.guard_defense(0, 6), 2)
        self.assertEqual(rules.guard_defense(2, 6), 6)
        self.assertEqual(rules.guard_defense(2, 4), 4)   # 宫门上限 4 截断

    def test_time_tax(self):
        self.assertEqual(rules.guard_time_tax("normal", 6), min(40, 10 + 30))
        self.assertEqual(rules.guard_time_tax("key_pass", 7), min(50, 15 + 35))
        self.assertEqual(rules.guard_time_tax("gate", 4), min(32, 12 + 20))
        self.assertEqual(rules.guard_time_tax("obstacle_node", 5), min(28, 8 + 25))

    def test_attack_value(self):
        self.assertEqual(rules.break_guard_attack_value(2, 0), 4)
        self.assertEqual(rules.break_guard_attack_value(1, 1), 5)
        self.assertEqual(rules.break_guard_attack_value(1, 1, break_order=True), 8)


class TestScore(unittest.TestCase):
    def test_delivery_base(self):
        self.assertEqual(rules.delivery_base_score(0), 120)     # 0 任务 50% 保底
        self.assertEqual(rules.delivery_base_score(90), 240)    # 达 90 拿满
        self.assertEqual(rules.delivery_base_score(200), 240)   # 封顶

    def test_good_and_freshness(self):
        self.assertEqual(rules.good_fruit_score(100), 180)
        self.assertEqual(rules.good_fruit_score(78), 140)
        self.assertEqual(rules.freshness_score(100), 180)
        self.assertEqual(rules.freshness_score(92.5), 166)

    def test_time(self):
        self.assertEqual(rules.raw_time_score(300), 35)
        self.assertEqual(rules.time_score(300, 90), 35)
        self.assertEqual(rules.time_score(300, 45), 17)         # floor(35*45/90)=17

    def test_task(self):
        self.assertEqual(rules.task_milestone_bonus(59), 0)
        self.assertEqual(rules.task_milestone_bonus(60), 15)
        self.assertEqual(rules.task_milestone_bonus(90), 35)
        self.assertEqual(rules.task_milestone_bonus(110), 50)
        self.assertEqual(rules.task_score(100), 135)
        self.assertEqual(rules.task_score(150), 180)            # 封顶
        self.assertEqual(rules.task_score(100, delivered=False), 80)  # 未交付封 80

    def test_bounty(self):
        self.assertEqual(rules.bounty_score(80, delivered=True), 100)
        self.assertEqual(rules.bounty_score(0, delivered=True), 0)
        self.assertEqual(rules.bounty_score(90, delivered=False), 25)

    def test_total(self):
        self.assertEqual(rules.total_score([240, 135, 180], penalty=5), 550)
        self.assertEqual(rules.total_score([10], penalty=100), 0)  # 最低 0


if __name__ == "__main__":
    unittest.main()
