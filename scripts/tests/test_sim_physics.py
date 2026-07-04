"""物理推进单测：移动帧数 / 鲜度损耗 / 天气倍率 / 好→坏转换 / 设卡公式 对齐 core/rules.py。"""

import unittest

import _pathsetup  # noqa: F401
from core import rules
from sim_engine import SimEngine
import sim_test_utils as u


class PhysicsTest(unittest.TestCase):
    def test_edge_crossing_frames_match_rules(self):
        """S01→S02(ROAD,30) 实际跨越帧数 == rules.frames_on_edge。"""
        eng = u.fresh_engine()
        red = eng.players["RED"]
        # advance-on-start：每帧 MOVE 续行，直到 move_accum >= to_station_move_amount
        need = rules.to_station_move_amount(30, "ROAD")
        per = rules.per_frame_move_amount(rules.BASE_MOVE_NONE, 1000)
        expected = -(-need // per)  # ceil
        frames = 0
        while red.pos == "S01" and frames < 200:
            eng.step({"RED": [{"action": "MOVE", "targetNodeId": "S02"}], "BLUE": []})
            frames += 1
        self.assertEqual(red.pos, "S02")
        self.assertEqual(frames, expected)

    def test_freshness_loss_matches_rules(self):
        """停靠帧鲜度损耗 == rules.freshness_loss(BASE, 1.0, 1.0)。"""
        eng = u.fresh_engine()
        before = eng.players["RED"].freshness
        eng.step({"RED": [], "BLUE": []})  # 空动作→停靠
        after = eng.players["RED"].freshness
        self.assertAlmostEqual(before - after, rules.freshness_loss(rules.FRESHNESS_LOSS_BASE))

    def test_freshness_loss_moving_uses_route_type(self):
        """移动中鲜度损耗用 FRESHNESS_LOSS_MOVE[routeType]（S01→S06 是 MOUNTAIN）。"""
        eng = u.fresh_engine()
        eng.step({"RED": [{"action": "MOVE", "targetNodeId": "S06"}], "BLUE": []})
        before = eng.players["RED"].freshness
        eng.step({"RED": [{"action": "MOVE", "targetNodeId": "S06"}], "BLUE": []})
        after = eng.players["RED"].freshness
        # S01→S06 MOUNTAIN 移动中
        self.assertEqual(eng.players["RED"].route_edge.route_type, "MOUNTAIN")
        self.assertAlmostEqual(before - after, rules.freshness_loss(rules.FRESHNESS_LOSS_MOVE["MOUNTAIN"]))

    def test_good_to_bad_threshold_crossing(self):
        """鲜度跨 90 阈值时 1 篎好果转坏。"""
        eng = u.fresh_engine()
        red = eng.players["RED"]
        red.freshness = 90.0  # 恰在阈值上，下一帧结算到 <90 触发转坏
        good_before = red.good_fruit
        eng.step({"RED": [], "BLUE": []})  # 停靠损耗 0.05 → 89.95 跨 90
        self.assertEqual(red.good_fruit, good_before - 1)
        self.assertEqual(red.bad_fruit, 1)

    def test_weather_move_multiplier(self):
        """暴雨命中水路时每帧移动量按 1350 倍率降低。"""
        self.assertEqual(rules.weather_move_multiplier("WATER", "HEAVY_RAIN"), 1350)
        self.assertEqual(rules.weather_move_multiplier("MOUNTAIN", "MOUNTAIN_FOG"), 1100)
        self.assertEqual(rules.weather_move_multiplier("ROAD", "HEAVY_RAIN"), 1000)

    def test_guard_formulas(self):
        """设卡防守值 / 强制通行税 / 攻坚值 对齐 rules。"""
        self.assertEqual(rules.guard_defense(2, 10), 6)   # 2 + 2*2
        self.assertEqual(rules.guard_defense(0, 10), 2)
        self.assertEqual(rules.break_guard_attack_value(1, 1, True), 1 * 2 + 1 * 3 + 3)
        self.assertEqual(rules.guard_time_tax("gate", 4), min(32, 12 + 4 * 5))
        self.assertEqual(rules.guard_time_tax("key_pass", 2), min(50, 15 + 2 * 5))


if __name__ == "__main__":
    unittest.main()
