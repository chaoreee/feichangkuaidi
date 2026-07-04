"""SimValidator 对账单测：over_data 报告分 == rules 独立重算；篡改后能检出。"""

import unittest

import _pathsetup  # noqa: F401
from sim_validator import validate, SimReconcileError
import sim_test_utils as u


class ValidatorTest(unittest.TestCase):
    def test_validate_passes_on_fresh_engine(self):
        """未交付态下 over_data 对账通过。"""
        eng = u.fresh_engine()
        for _ in range(10):
            eng.step({"RED": [], "BLUE": []})
        over = eng.build_over_data()
        result = validate(eng, over)
        self.assertIn("RED", result)

    def test_validate_catches_overdata_corruption(self):
        """篡改 over_data 报告分后对账应失败。"""
        eng = u.fresh_engine()
        for _ in range(10):
            eng.step({"RED": [], "BLUE": []})
        over = eng.build_over_data()
        over["players"][0]["totalScore"] += 100  # 篡改报告分
        with self.assertRaises(SimReconcileError):
            validate(eng, over)

    def test_validate_delivered_scenario(self):
        """构造交付场景：手动标 delivered + deliver_round，over_data 对账通过且分>0。"""
        eng = u.fresh_engine()
        red = eng.players["RED"]
        red.delivered = True
        red.deliver_round = 470
        red.task_score = 30
        red.good_fruit = 90
        red.freshness = 80.0
        over = eng.build_over_data()
        result = validate(eng, over)
        self.assertGreater(result["RED"], 0)


if __name__ == "__main__":
    unittest.main()
