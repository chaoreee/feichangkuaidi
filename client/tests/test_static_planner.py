"""Phase B 静态规划器单测（Iter 26，docs/p0_attribution_batch2.md）。

真实 30 局 trace 证伪"任务"杠杆、确证"鲜度"为真实杠杆（+19/局，质量路线投影 +24）。
static_planner 把"早交付 vs 保鲜度"当优化问题：候选路线（时间最优/鲜度最优）× 冰鉴用量
→ 投影终局分最高者。默认关（ENABLE_STATIC_PLANNER），作 variant 仿真 A/B 后合入。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core import rules  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy import static_planner as sp  # noqa: E402
from strategy.projection import project_final_score, freshness_loss_for_path  # noqa: E402
from strategy.decision import GameContext, DecisionEngine  # noqa: E402
from protocol.enums import ResourceType  # noqa: E402

PID = 1001

# 双路线地图 S01→S05：
#   直路（时间最优）：S01 -MOUNTAIN(d=28)-> S05        （50 帧，损耗 3.5）
#   绕路（鲜度最优）：S01 -WATER(d=22)-> S03 -WATER(d=22)-> S05（56 帧，损耗 2.52）
# 鲜度绕路投影终局分更高（损耗差 ×1.8 > 帧差 ×0.117 + MIN_ROUTE_GAIN）→ plan_route 改道。
START_DATA = {
    "matchId": "t", "durationRound": 600,
    "nodes": [
        {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "S03", "type": "STATION", "x": 1, "y": 2},
        {"nodeId": "S05", "type": "FINISH", "x": 3, "y": 0, "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S05", "routeType": "MOUNTAIN", "distance": 28, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "WATER", "distance": 22, "bidirectional": True},
        {"edgeId": "E3", "fromNodeId": "S03", "toNodeId": "S05", "routeType": "WATER", "distance": 22, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "S01", "terminalNodeIds": ["S05"], "safeZoneNodeIds": ["S05"]}}},
}


def _world(node="S01", fresh=100.0, good=100, verified=True, ice=0, task=150, rnd=100):
    inq = {"round": rnd, "phase": "NORMAL",
           "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE",
                        "currentNodeId": node, "verified": verified,
                        "goodFruit": good, "freshness": fresh, "taskScore": task,
                        "resources": {"ICE_BOX": ice}}]}
    return WorldState(inq, PID)


class TestFreshnessOptimalPath(unittest.TestCase):
    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map

    def test_picks_lower_loss_water_detour_over_mountain(self):
        """鲜度最优选 WATER 绕路（2.52 损耗）而非 MOUNTAIN 直路（3.5）。"""
        p_time, _ = self.gm.time_optimal_path("S01", "S05")
        p_fresh, loss = sp.freshness_optimal_path(self.gm, "S01", "S05", weather_coef=1.0)
        self.assertEqual(p_time, ["S01", "S05"])          # 时间最优走直路
        self.assertEqual(p_fresh, ["S01", "S03", "S05"])  # 鲜度最优走绕路
        self.assertAlmostEqual(loss, 2.52, places=2)

    def test_same_node_returns_self(self):
        p, loss = sp.freshness_optimal_path(self.gm, "S01", "S01")
        self.assertEqual(p, ["S01"])
        self.assertEqual(loss, 0.0)

    def test_unreachable_returns_empty(self):
        p, loss = sp.freshness_optimal_path(self.gm, "S01", "S99")
        self.assertEqual(p, [])
        self.assertEqual(loss, float("inf"))

    def test_blocked_node_avoided(self):
        """S03 被阻塞 → 鲜度最优退回 MOUNTAIN 直路。"""
        p, _ = sp.freshness_optimal_path(self.gm, "S01", "S05", blocked={"S03"})
        self.assertEqual(p, ["S01", "S05"])


class TestProjectRoute(unittest.TestCase):
    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map

    def test_no_ice_matches_project_final_score(self):
        """无冰鉴时 project_route 终局分 = project_final_score(fresh − route_loss, ...)。"""
        w = _world(node="S01", fresh=100.0, good=100, verified=True, ice=0, task=150, rnd=100)
        path = ["S01", "S05"]  # MOUNTAIN 直路，已验核
        loss = freshness_loss_for_path(self.gm, path, 1.0, verify_frames=0)
        frames = sp.path_frames(self.gm, path)
        proj = sp.project_route(w, w.me, self.gm, path, "S05", 0, self.ctx, 1.0)
        self.assertIsNotNone(proj)
        expected_score = project_final_score(
            100 + frames, 150, 100, max(0.0, 100.0 - loss), duration=600)
        self.assertAlmostEqual(proj["score"], expected_score, places=4)
        self.assertEqual(proj["deliver_frame"], 100 + frames)
        self.assertAlmostEqual(proj["final_fresh"], 100.0 - loss, places=4)

    def test_ice_restores_freshness_and_costs_frames(self):
        """k 次冰鉴：final_fresh +10k（封顶 100）、deliver_frame +k、crossing 抵 k。"""
        w = _world(node="S01", fresh=80.0, good=100, verified=True, ice=3, task=150, rnd=100)
        path = ["S01", "S05"]
        loss = freshness_loss_for_path(self.gm, path, 1.0, verify_frames=0)
        frames = sp.path_frames(self.gm, path)
        p0 = sp.project_route(w, w.me, self.gm, path, "S05", 0, self.ctx, 1.0)
        p2 = sp.project_route(w, w.me, self.gm, path, "S05", 2, self.ctx, 1.0)
        # 80 − loss（>0）+ 20，封顶 100
        self.assertAlmostEqual(p2["final_fresh"], min(100.0, 80.0 - loss + 20.0), places=4)
        self.assertEqual(p2["deliver_frame"], p0["deliver_frame"] + 2)
        # 冰鉴阻止 2 次 crossing → final_good 比 0 冰鉴多 2（若 0 冰鉴有 ≥2 次 crossing）
        self.assertGreaterEqual(p2["final_good"], p0["final_good"])

    def test_ice_raises_score_when_freshness_lever_dominates(self):
        """鲜度杠杆主导时，用冰鉴的投影分 > 不用（+10 鲜度 ×1.8 > −1 帧时间成本）。"""
        w = _world(node="S01", fresh=80.0, good=100, verified=True, ice=3, task=150, rnd=100)
        path = ["S01", "S05"]
        p0 = sp.project_route(w, w.me, self.gm, path, "S05", 0, self.ctx, 1.0)
        p1 = sp.project_route(w, w.me, self.gm, path, "S05", 1, self.ctx, 1.0)
        self.assertGreater(p1["score"], p0["score"])

    def test_none_on_empty_path(self):
        w = _world()
        self.assertIsNone(sp.project_route(w, w.me, self.gm, [], "S05", 0, self.ctx, 1.0))
        self.assertIsNone(sp.project_route(w, w.me, self.gm, ["S01"], "S05", 0, self.ctx, 1.0))


class TestPlanRoute(unittest.TestCase):
    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map

    def test_picks_freshness_route_when_it_projects_higher(self):
        """无冰鉴预算时（KEEP=0），长路线鲜度绕路投影分高出 ≥MIN_ROUTE_GAIN → 改道。

        注：有冰鉴预算时两侧鲜度都封顶 100、时间最优反超——冰鉴才是 +24 主驱动（见下一测试）。
        本测试把 STATIC_PLANNER_ICE_KEEP 临时置 0 以隔离"路线选择"维度。
        """
        w = _world(node="S01", fresh=100.0, good=100, verified=True, ice=0, task=150, rnd=100)
        old_keep = config.STATIC_PLANNER_ICE_KEEP
        config.STATIC_PLANNER_ICE_KEEP = 0
        try:
            path, score = sp.plan_route(w, w.me, self.gm, "S01", "S05", "S05", self.ctx)
            self.assertEqual(path, ["S01", "S03", "S05"])  # 改走鲜度绕路
            self.assertGreater(score, 0)
        finally:
            config.STATIC_PLANNER_ICE_KEEP = old_keep

    def test_with_ice_budget_keeps_time_optimal(self):
        """有冰鉴预算（KEEP=3）时两侧鲜度封顶 100，时间最优（直路更短）反超 → 保直路。

        这反映实战常态：冰鉴足以补偿损耗差时，路线选择让位给时间最优（冰鉴是主驱动）。
        """
        w = _world(node="S01", fresh=100.0, good=100, verified=True, ice=3, task=150, rnd=100)
        path, _ = sp.plan_route(w, w.me, self.gm, "S01", "S05", "S05", self.ctx)
        self.assertEqual(path, ["S01", "S05"])  # 时间最优直路

    def test_keeps_time_optimal_when_gain_below_threshold(self):
        """鲜度绕路增益 < MIN_ROUTE_GAIN（抬高阈值至 50）→ 即使绕路投影略高也保时间最优。"""
        w = _world(node="S01", fresh=100.0, good=100, verified=True, ice=0, task=150, rnd=100)
        old_keep = config.STATIC_PLANNER_ICE_KEEP
        old_gain = config.STATIC_PLANNER_MIN_ROUTE_GAIN
        config.STATIC_PLANNER_ICE_KEEP = 0
        config.STATIC_PLANNER_MIN_ROUTE_GAIN = 50.0
        try:
            path, _ = sp.plan_route(w, w.me, self.gm, "S01", "S05", "S05", self.ctx)
            self.assertEqual(path, ["S01", "S05"])  # 增益 ~1 < 50 → 保时间最优
        finally:
            config.STATIC_PLANNER_ICE_KEEP = old_keep
            config.STATIC_PLANNER_MIN_ROUTE_GAIN = old_gain

    def test_fallback_on_exception(self):
        """异常输入不抛出，回落时间最优。"""
        w = _world(node="S01", fresh=100.0)
        # 传入非法 terminal 仍不抛
        path, _ = sp.plan_route(w, w.me, self.gm, "S01", "S05", None, self.ctx)
        self.assertIn(path[0], ("S01",))


class TestDecisionIntegration(unittest.TestCase):
    """flag-off 行为不变；flag-on 冰鉴阈值/囤积提升、路线走规划器。"""

    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map

    def test_flag_off_select_path_equals_time_optimal(self):
        w = _world(node="S01", fresh=100.0, verified=True)
        eng = DecisionEngine(self.ctx)
        path, cost = eng._select_path(w, w.me, self.gm, "S01", "S05", frozenset(), "S05")
        tp, tc = self.gm.time_optimal_path("S01", "S05", blocked=frozenset())
        self.assertEqual(path, tp)
        self.assertEqual(cost, tc)

    def test_flag_on_freshness_rescue_uses_raised_threshold(self):
        """flag-on：鲜度 90（≥baseline 阈值 78 但 < STATIC_PLANNER 91）→ 用冰鉴。"""
        w = _world(node="S01", fresh=90.0, ice=2)
        eng = DecisionEngine(self.ctx)
        old = config.ENABLE_STATIC_PLANNER
        config.ENABLE_STATIC_PLANNER = True
        try:
            act = eng._freshness_rescue(w, w.me)
            self.assertIsNotNone(act)  # 90 < 91 → 触发
        finally:
            config.ENABLE_STATIC_PLANNER = old

    def test_flag_off_freshness_rescue_skips_at_90(self):
        """flag-off：鲜度 90 ≥ baseline 阈值 78 → 不用冰鉴（baseline 行为不变）。"""
        w = _world(node="S01", fresh=90.0, ice=2)
        eng = DecisionEngine(self.ctx)
        self.assertIsNone(eng._freshness_rescue(w, w.me))

    def test_flag_on_ice_keep_raised(self):
        """flag-on：_maybe_claim 期望囤冰鉴到 STATIC_PLANNER_ICE_KEEP(3)。"""
        # S03 无资源 → 不领；这里只验 ice_keep 提升后"持有<3 且有货"才触发的逻辑路径不抛。
        w = _world(node="S01", fresh=100.0, ice=1)
        eng = DecisionEngine(self.ctx)
        old = config.ENABLE_STATIC_PLANNER
        config.ENABLE_STATIC_PLANNER = True
        try:
            eng._maybe_claim(w, w.me, self.gm, "S01", "S05")  # 不应抛异常
        finally:
            config.ENABLE_STATIC_PLANNER = old


if __name__ == "__main__":
    unittest.main()
