"""`analysis.route_planner_eval` 单测——Iter 36 §1 资源感知路线重评。

验证逐帧 walker（马感知 + 冰鉴 post-hoc + 处理站/验核）：
1. 单边帧数/损耗手算一致（S01→S06 MOUNTAIN 44：79 帧 / 5.53 损耗）。
2. 马感知：SHORT_HORSE 路线比无马路线帧数更少。
3. 冰鉴 post-hoc：2 冰鉴 → final_fresh 封顶 100、crossings 抵消。
4. 大路 Δscore > 山路（杠杆方向）。
5. 候选路线边存在性（五命名路线每段边在 samples GameMap 中存在）。
6. frame_optimal = 山路（Dijkstra 帧最优，对齐 Iter 35 §1.3）。
7. static_planner 在真实图选大路（§1.3）。
8. 对手签名分类（_classify_by_signature）。
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "client"))

from core import rules  # noqa: E402
from analysis import route_planner_eval as rpe  # noqa: E402


def _setup():
    start_data, res_by_node, _cfg = rpe.load_samples_start_data()
    gm = rpe.build_game_map(start_data)
    return gm, res_by_node


class TestWalkerLegs(unittest.TestCase):
    def setUp(self):
        self.gm, self.res = _setup()

    def test_single_leg_mountain_frames_and_loss(self):
        """S01→S06 MOUNTAIN d=44：amount=ceil(44×1780)=78320 → 79 帧 × 0.07 = 5.53 损耗。"""
        # 路径 S01→S06，无资源/处理/验核——纯单边移动
        proj = rpe.walk_route(self.gm, ["S01", "S06"], {}, {})
        self.assertEqual(proj["move_frames"], 79)
        # route_loss = 100 - fresh_no_ice = 79 × 0.07 = 5.53
        self.assertAlmostEqual(proj["route_loss"], 5.53, places=2)

    def test_horse_reduces_frames(self):
        """S08 有 SHORT_HORSE：领+用后 S08→S10 段帧数 < 无马帧数。"""
        res = {"S08": {"SHORT_HORSE": 1}}
        path = ["S08", "S10"]  # 纯移动段（S08/S10 非处理站）
        # 无马
        proj_no = rpe.walk_route(self.gm, path, {}, {})
        # 有马（需 S08 在 res 表）
        proj_horse = rpe.walk_route(self.gm, path, res, {})
        # 马使移动帧减少（SHORT_HORSE 1150 > 1000）
        self.assertLess(proj_horse["move_frames"], proj_no["move_frames"])
        # 用马：claim 2 + use 1 = 3 stop frames
        self.assertEqual(proj_horse["stop_frames"], 3)

    def test_ice_posthoc_caps_freshness_and_prevents_crossing(self):
        """2 冰鉴：fresh_no_ice≈79 跨 90/80 两阈，2 ice 抵 2 crossing → good=100、fresh 封顶。"""
        # 山路（1 冰鉴）vs 大路（2 冰鉴）的 ice_uses / crossings
        mtn = rpe.walk_route(self.gm, rpe.CANDIDATE_ROUTES["mountain"], self.res, {})
        main = rpe.walk_route(self.gm, rpe.CANDIDATE_ROUTES["mainroad"], self.res, {})
        self.assertEqual(mtn["ice_inv"], 1)
        self.assertEqual(main["ice_inv"], 2)
        # 大路 2 冰鉴恰抵 2 crossing（fresh_no_ice 跨 90/80）
        self.assertEqual(main["crossings"], 0)
        self.assertEqual(main["final_good"], 100)
        # final_fresh 封顶接近 100
        self.assertGreater(main["final_fresh"], 95.0)


class TestCandidates(unittest.TestCase):
    def setUp(self):
        self.gm, self.res = _setup()
        self.results = rpe.evaluate_all(self.gm, self.res)

    def test_all_named_routes_valid(self):
        """五命名路线每段边在 samples GameMap 中存在。"""
        for name, path in rpe.CANDIDATE_ROUTES.items():
            for i in range(len(path) - 1):
                self.assertIsNotNone(self.gm.edge_between(path[i], path[i + 1]),
                                     "%s 段 %s→%s 无边" % (name, path[i], path[i + 1]))

    def test_frame_optimal_is_mountain(self):
        """Dijkstra 帧最优 = 山路（对齐 Iter 35 §1.3：三准则重合，山路 329 帧最优）。"""
        fo = self.results.get("frame_optimal")
        self.assertIsNotNone(fo)
        self.assertEqual(fo["path"], rpe.CANDIDATE_ROUTES["mountain"])

    def test_mainroad_beats_mountain(self):
        """大路 Δscore vs 山路 > 0（杠杆方向确认）。"""
        main = self.results["mainroad"]
        mtn = self.results["mountain"]
        self.assertGreater(main["score"], mtn["score"])
        d = main["delta_vs_mountain"]
        self.assertGreater(d["score"], 0)
        self.assertGreater(d["fresh"], 0)

    def test_mainroad_higher_freshness(self):
        """大路端鲜度 > 山路（双冰鉴 + ROAD 低损耗）。"""
        self.assertGreater(self.results["mainroad"]["final_fresh"],
                           self.results["mountain"]["final_fresh"])


class TestStaticPlannerPick(unittest.TestCase):
    def test_plan_route_picks_mainroad(self):
        """§1.3：static_planner 在真实图选大路。"""
        start_data, res_by_node, _cfg = rpe.load_samples_start_data()
        pick = rpe.static_planner_pick(start_data, res_by_node)
        self.assertTrue(pick["is_mainroad"], "plan_route 选 %s 非大路" % pick["path"])
        self.assertEqual(pick["path"], rpe.CANDIDATE_ROUTES["mainroad"])


class TestOpponentSignature(unittest.TestCase):
    def test_classify_by_signature(self):
        self.assertEqual(rpe._classify_by_signature(
            ["S01", "S02", "S03", "S07", "S09", "S10", "S13", "S14", "S15"]), "mainroad")
        self.assertEqual(rpe._classify_by_signature(
            ["S01", "S06", "S08", "S10", "S13", "S14", "S15"]), "mountain")
        self.assertEqual(rpe._classify_by_signature(
            ["S01", "S02", "S04", "S05", "S09", "S10", "S13", "S14", "S15"]), "water")
        self.assertEqual(rpe._classify_by_signature(
            ["S01", "S02", "S03", "S09", "S10"]), "other")

    def test_cross_validate_returns_none_when_no_dir(self):
        self.assertIsNone(rpe.cross_validate_opponent("/nonexistent/dir"))


if __name__ == "__main__":
    unittest.main()
