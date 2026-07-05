"""Iter 36 §1.5 真实天气审计单测。"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CLIENT = os.path.join(_ROOT, "client")
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from analysis import route_weather_audit as rwa  # noqa: E402
from analysis.route_planner_eval import (  # noqa: E402
    build_game_map, load_samples_start_data, walk_route, CANDIDATE_ROUTES,
)

_SAMPLES = os.path.join(_ROOT, "samples", "map_config.json")


def _gm():
    sd, res, _ = load_samples_start_data(_SAMPLES)
    return build_game_map(sd), res


class TestParseWeather(unittest.TestCase):
    def test_extract_sequence(self):
        text = ("# match_x\nF r1 n=S01 st=IDLE\n"
                "F r84 st=MOVING w=HOT\n"
                "F r235 w=HEAVY_RAIN on=S02\n"
                "F r345 w=MOUNTAIN_FOG\n")
        seq = rwa.parse_weather_sequence(text)
        self.assertEqual(seq, [(84, "HOT"), (235, "HEAVY_RAIN"), (345, "MOUNTAIN_FOG")])

    def test_no_weather(self):
        self.assertEqual(rwa.parse_weather_sequence("F r1 n=S01\nF r2 st=MOVING\n"), [])

    def test_ignores_non_F_lines(self):
        text = "N S01 S02\nF r10 w=HOT\nA r11 MOVE\n"
        self.assertEqual(rwa.parse_weather_sequence(text), [(10, "HOT")])


class TestWtypeAt(unittest.TestCase):
    def test_before_first_event_clear(self):
        seq = [(84, "HOT"), (235, "HEAVY_RAIN")]
        self.assertIsNone(rwa._wtype_at(seq, 1))
        self.assertIsNone(rwa._wtype_at(seq, 83))

    def test_within_phase(self):
        seq = [(84, "HOT"), (235, "HEAVY_RAIN")]
        self.assertEqual(rwa._wtype_at(seq, 84), "HOT")
        self.assertEqual(rwa._wtype_at(seq, 200), "HOT")
        self.assertEqual(rwa._wtype_at(seq, 235), "HEAVY_RAIN")
        self.assertEqual(rwa._wtype_at(seq, 400), "HEAVY_RAIN")

    def test_none_seq(self):
        self.assertIsNone(rwa._wtype_at(None, 100))


class TestWeatherSummary(unittest.TestCase):
    def test_caps_at_max_round(self):
        seq = [(84, "HOT"), (235, "HEAVY_RAIN"), (471, "HOT")]
        ws = rwa._weather_summary(seq, 374)
        # 471 事件 > max_round → 丢弃；末段 HEAVY_RAIN 截到 374
        types = [t for a, b, t in ws["phases"]]
        self.assertEqual(types, ["CLEAR", "HOT", "HEAVY_RAIN"])
        self.assertTrue(all(b <= 374 for a, b, t in ws["phases"]))

    def test_empty_seq(self):
        ws = rwa._weather_summary([], 400)
        self.assertEqual(ws["phases"], [(1, 400, "CLEAR")])
        self.assertEqual(ws["bad_rounds"], 0)


class TestAuditGame(unittest.TestCase):
    def setUp(self):
        self.gm, self.res = _gm()

    def test_clear_weather_matches_section1(self):
        """weather_seq=None → Δ = +20（与 §1 coef=1.0 上界一致）。"""
        res = rwa.audit_game(self.gm, self.res, [])
        self.assertEqual(res["delta_clear"], 20.0)
        self.assertEqual(res["delta_real"]["score"], 20.0)
        self.assertEqual(res["shrinkage"], 0.0)

    def test_hot_does_not_shrink_lever(self):
        """HOT 全程：大路 2 冰鉴抵更多 crossing → Δ 不缩水（≥ clear 上界）。

        实测 Δ=+20（=clear）：HOT 对双方鲜度同倍惩罚，大路多 30 帧的额外损耗被
        第 2 冰鉴抵 crossing 抵消 → 中性，不缩水。
        """
        res = rwa.audit_game(self.gm, self.res, [(1, "HOT")])
        self.assertGreaterEqual(res["delta_real"]["score"], res["delta_clear"] - 0.01)
        self.assertGreater(res["delta_real"]["score"], 0)

    def test_mountain_fog_helps_mainroad(self):
        """MOUNTAIN_FOG 减速山路 MOUNTAIN 边 → 山路多帧多损耗 → Δ > clear。"""
        res = rwa.audit_game(self.gm, self.res, [(1, "MOUNTAIN_FOG")])
        self.assertGreater(res["delta_real"]["score"], res["delta_clear"] - 0.01)

    def test_mainroad_always_beats_mountain(self):
        """各类天气下大路仍净正（杠杆稳健）。"""
        for seq in [[], [(1, "HOT")], [(1, "HEAVY_RAIN")],
                    [(1, "MOUNTAIN_FOG")], [(50, "HOT"), (200, "HEAVY_RAIN")]]:
            res = rwa.audit_game(self.gm, self.res, seq)
            self.assertIsNotNone(res, "seq=%s" % seq)
            self.assertGreater(res["delta_real"]["score"], 0, "seq=%s" % seq)

    def test_extra_frame_weather_extracted(self):
        res = rwa.audit_game(self.gm, self.res, [(1, "HOT")])
        self.assertIn("HOT", res["extra_frame_weather"])


class TestWalkRouteWeatherHook(unittest.TestCase):
    """weather_seq 接入 route_planner_eval.walk_route 的回归。"""

    def setUp(self):
        self.gm, self.res = _gm()

    def test_none_weather_identical_to_no_opt(self):
        """weather_seq=None 与不传 opts 等价（向后兼容）。"""
        a = walk_route(self.gm, CANDIDATE_ROUTES["mountain"], self.res, {})
        b = walk_route(self.gm, CANDIDATE_ROUTES["mountain"], self.res,
                       {"weather_seq": None})
        self.assertEqual(a["score"], b["score"])
        self.assertEqual(a["deliver_frame"], b["deliver_frame"])

    def test_hot_weather_lowers_freshness(self):
        """HOT 全程 → 端鲜度（无冰）低于无天气。"""
        clear = walk_route(self.gm, CANDIDATE_ROUTES["mountain"], self.res, {})
        hot = walk_route(self.gm, CANDIDATE_ROUTES["mountain"], self.res,
                         {"weather_seq": [(1, "HOT")]})
        self.assertLess(hot["fresh_no_ice"], clear["fresh_no_ice"])

    def test_mountain_fog_adds_frames_to_mountain_route(self):
        """MOUNTAIN_FOG 减速山路 MOUNTAIN 边 → 交付帧增多。"""
        clear = walk_route(self.gm, CANDIDATE_ROUTES["mountain"], self.res, {})
        fog = walk_route(self.gm, CANDIDATE_ROUTES["mountain"], self.res,
                         {"weather_seq": [(1, "MOUNTAIN_FOG")]})
        self.assertGreater(fog["deliver_frame"], clear["deliver_frame"])


if __name__ == "__main__":
    unittest.main()
