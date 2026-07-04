"""确定性单测：同 seed 两次自博弈 → Report 关键字段一致（忽略墙上时钟时间戳）。"""

import os
import shutil
import tempfile
import unittest

import _pathsetup  # noqa: F401
from analysis.parser import parse_log
import sim_server


def _play_and_parse(seed, out_dir):
    sim_server.play_one_game(seed=seed, variant="baseline", out_dir=out_dir, verbose=False)
    logs = sorted(f for f in os.listdir(out_dir) if f.endswith(".log"))
    # RED 日志（playerId 1001）
    red_log = next(f for f in logs if f.endswith("_1001.log"))
    return parse_log(os.path.join(out_dir, red_log), source="sim", variant="baseline")


class DeterminismTest(unittest.TestCase):
    def test_same_seed_same_report(self):
        d1 = tempfile.mkdtemp(prefix="sim_det1_")
        d2 = tempfile.mkdtemp(prefix="sim_det2_")
        try:
            r1 = _play_and_parse(11, d1)
            r2 = _play_and_parse(11, d2)
            self.assertIsNotNone(r1)
            self.assertIsNotNone(r2)
            self.assertEqual(r1.get("outcome"), r2.get("outcome"))
            self.assertEqual(r1.get("delivery", {}).get("me", {}).get("frame"),
                             r2.get("delivery", {}).get("me", {}).get("frame"))
            self.assertEqual(r1.get("finalScore", {}).get("me", {}).get("total"),
                             r2.get("finalScore", {}).get("me", {}).get("total"))
            self.assertEqual(r1.get("finalScore", {}).get("opp", {}).get("total"),
                             r2.get("finalScore", {}).get("opp", {}).get("total"))
        finally:
            shutil.rmtree(d1, ignore_errors=True)
            shutil.rmtree(d2, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
