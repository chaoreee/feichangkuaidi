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

# 远冰地图（冰源 S03 偏远，绕路代价 >> 鲜度收益）：S01-S05 ROAD 短直，S01-S03-S05 WATER 长绕。
# 用于验证 ΔEV 门拒绝亏交易（通用策略在"鲜度昂贵"图上应中性）。
FAR_ICE_MAP = {
    "matchId": "t2", "durationRound": 600,
    "nodes": [
        {"nodeId": "S01", "type": "START", "x": 0, "y": 0, "start": True},
        {"nodeId": "S03", "type": "STATION", "x": 5, "y": 5},
        {"nodeId": "S05", "type": "FINISH", "x": 3, "y": 0, "terminal": True},
    ],
    "edges": [
        {"edgeId": "F1", "fromNodeId": "S01", "toNodeId": "S05", "routeType": "ROAD", "distance": 20, "bidirectional": True},
        {"edgeId": "F2", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "WATER", "distance": 40, "bidirectional": True},
        {"edgeId": "F3", "fromNodeId": "S03", "toNodeId": "S05", "routeType": "WATER", "distance": 40, "bidirectional": True},
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


def _joint_world(node="S01", fresh=100.0, good=100, verified=True, ice=0, task=100, rnd=100,
                 ice_nodes=None, tasks=None):
    """带冰源节点 + 任务实例的 WorldState（供联合规划器沿途 task/ice 建模测试）。

    ice_nodes：节点 ID 列表，每个在 inq.nodes 里置 resourceStock={ICE_BOX:1}（world.node_states 可见）。
    tasks：任务 dict 列表（{nodeId, score, processRound, active}），入 inq.tasks。
    """
    nodes = [{"nodeId": nid, "nodeType": "STATION", "resourceStock": {"ICE_BOX": 1}}
             for nid in (ice_nodes or [])]
    inq = {"round": rnd, "phase": "NORMAL",
           "players": [{"playerId": PID, "teamId": "RED", "state": "IDLE",
                        "currentNodeId": node, "verified": verified,
                        "goodFruit": good, "freshness": fresh, "taskScore": task,
                        "resources": {"ICE_BOX": ice}}],
           "nodes": nodes,
           "tasks": tasks or []}
    return WorldState(inq, PID)


def _task(nid, score=20, pr=3):
    return {"taskId": "TK_%s" % nid, "nodeId": nid, "score": score,
            "processRound": pr, "active": True}


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
        """无冰鉴预算（库存 0、沿途无冰源）时，鲜度绕路投影分高出 ≥MIN_ROUTE_GAIN → 改道。

        注：有冰鉴预算时两侧鲜度都封顶 100、时间最优反超——冰鉴才是 +24 主驱动（见下一测试）。
        本测试地图无冰源/任务点，隔离"纯路线选择"维度（ice_budget=0）。
        """
        w = _world(node="S01", fresh=100.0, good=100, verified=True, ice=0, task=150, rnd=100)
        path, score = sp.plan_route(w, w.me, self.gm, "S01", "S05", "S05", self.ctx)
        self.assertEqual(path, ["S01", "S03", "S05"])  # 改走鲜度绕路
        self.assertGreater(score, 0)

    def test_with_ice_budget_keeps_time_optimal(self):
        """有冰鉴预算（库存 3、沿途无冰源）时两侧鲜度封顶 100，时间最优（直路更短）反超 → 保直路。

        这反映实战常态：冰鉴足以补偿损耗差时，路线选择让位给时间最优（冰鉴是主驱动）。
        """
        w = _world(node="S01", fresh=100.0, good=100, verified=True, ice=3, task=150, rnd=100)
        path, _ = sp.plan_route(w, w.me, self.gm, "S01", "S05", "S05", self.ctx)
        self.assertEqual(path, ["S01", "S05"])  # 时间最优直路

    def test_keeps_time_optimal_when_gain_below_threshold(self):
        """鲜度绕路增益 < MIN_ROUTE_GAIN（抬高阈值至 50）→ 即使绕路投影略高也保时间最优。"""
        w = _world(node="S01", fresh=100.0, good=100, verified=True, ice=0, task=150, rnd=100)
        old_gain = config.STATIC_PLANNER_MIN_ROUTE_GAIN
        config.STATIC_PLANNER_MIN_ROUTE_GAIN = 50.0
        try:
            path, _ = sp.plan_route(w, w.me, self.gm, "S01", "S05", "S05", self.ctx)
            self.assertEqual(path, ["S01", "S05"])  # 增益 ~1 < 50 → 保时间最优
        finally:
            config.STATIC_PLANNER_MIN_ROUTE_GAIN = old_gain

    def test_fallback_on_exception(self):
        """异常输入不抛出，回落时间最优。"""
        w = _world(node="S01", fresh=100.0)
        # 传入非法 terminal 仍不抛
        path, _ = sp.plan_route(w, w.me, self.gm, "S01", "S05", None, self.ctx)
        self.assertIn(path[0], ("S01",))

    def test_efficiency_gate_rejects_low_ratio_long_detour(self):
        """长绕路(extra≥15) 投影增益为正但 gain/extra < MIN_ROUTE_EFFICIENCY → 保时间最优。

        FAR_ICE+task：gain=+20、extra=77、ratio≈0.26。抬高 MIN_ROUTE_EFFICIENCY=0.5、
        压低 MIN_ROUTE_GAIN=0（隔离效率门为唯一拒绝源）→ 效率门拒，保直送。
        对应 v2 失败模式：投影 +7/+60=0.12 的低效长绕路被采纳致 −3.7。
        """
        ctx = GameContext(PID, "RED", 0, FAR_ICE_MAP)
        gm = ctx.game_map
        w = _joint_world(task=100, ice_nodes=["S03"], tasks=[_task("S03", 20, 3)])
        old_gain = config.STATIC_PLANNER_MIN_ROUTE_GAIN
        old_eff = config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY
        config.STATIC_PLANNER_MIN_ROUTE_GAIN = 0.0      # 关绝对门，隔离效率门
        config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY = 0.5  # > 0.26 → 拒
        try:
            path, _ = sp.plan_route(w, w.me, gm, "S01", "S05", "S05", ctx)
            self.assertEqual(path, ["S01", "S05"])  # 效率门拒低效长绕路
        finally:
            config.STATIC_PLANNER_MIN_ROUTE_GAIN = old_gain
            config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY = old_eff

    def test_efficiency_gate_accepts_high_ratio_long_detour(self):
        """长绕路 gain/extra ≥ MIN_ROUTE_EFFICIENCY → 改道（效率门放行）。

        同 FAR_ICE+task（ratio≈0.26），MIN_ROUTE_EFFICIENCY=0.1（< 0.26）→ 放行改道。
        证明效率门是阈值门而非"长绕路一律拒"。
        """
        ctx = GameContext(PID, "RED", 0, FAR_ICE_MAP)
        gm = ctx.game_map
        w = _joint_world(task=100, ice_nodes=["S03"], tasks=[_task("S03", 20, 3)])
        old_gain = config.STATIC_PLANNER_MIN_ROUTE_GAIN
        old_eff = config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY
        config.STATIC_PLANNER_MIN_ROUTE_GAIN = 0.0
        config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY = 0.1  # < 0.26 → 放行
        try:
            path, _ = sp.plan_route(w, w.me, gm, "S01", "S05", "S05", ctx)
            self.assertEqual(path, ["S01", "S03", "S05"])  # 效率门放行
        finally:
            config.STATIC_PLANNER_MIN_ROUTE_GAIN = old_gain
            config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY = old_eff

    def test_short_detour_bypasses_efficiency_gate(self):
        """短绕路(extra<15) 时间成本估计可信，跳过效率门，仅绝对增益门把关。

        START_DATA 鲜度绕路 extra=6<15。即使 MIN_ROUTE_EFFICIENCY=999（若生效必拒），
        仍因 extra<15 跳过效率门、过绝对增益门 → 改道。
        """
        w = _world(node="S01", fresh=100.0, good=100, verified=True, ice=0, task=150, rnd=100)
        old_eff = config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY
        config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY = 999.0  # 若对短绕路生效必拒
        try:
            path, _ = sp.plan_route(w, w.me, self.gm, "S01", "S05", "S05", self.ctx)
            self.assertEqual(path, ["S01", "S03", "S05"])  # 短绕路跳过效率门 → 仍改道
        finally:
            config.STATIC_PLANNER_MIN_ROUTE_EFFICIENCY = old_eff


class TestDecisionIntegration(unittest.TestCase):
    """flag-off 行为不变；flag-on 冰鉴阈值/囤积提升、路线走规划器。"""

    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map
        # Iter 36 §2：flag 默认开。本类测 flag-off baseline 行为（test_flag_on_* 各自强制开）。
        self._old_sp = config.ENABLE_STATIC_PLANNER
        config.ENABLE_STATIC_PLANNER = False

    def tearDown(self):
        config.ENABLE_STATIC_PLANNER = self._old_sp

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


class TestJointModel(unittest.TestCase):
    """联合 task/ice 建模：_path_pickups + project_route 沿途正确计 task/ice（v1 冻结 task_base 的补全）。"""

    def setUp(self):
        self.ctx = GameContext(PID, "RED", 0, START_DATA)
        self.gm = self.ctx.game_map

    def test_path_pickups_credits_task_and_ice(self):
        """S03 有 task(score20/pr3) + ice → 沿 [S01,S03,S05] 领 1 任务、收 1 篓冰。"""
        w = _joint_world(task=100, ice_nodes=["S03"], tasks=[_task("S03", 20, 3)])
        td, tf, ic, ifr = sp._path_pickups(w, w.me, ["S01", "S03", "S05"])
        self.assertEqual(td, 20)
        self.assertEqual(tf, 3)
        self.assertEqual(ic, 1)
        self.assertEqual(ifr, sp._ICE_CLAIM_FRAMES)

    def test_path_pickups_caps_task_at_130(self):
        """task_base 已 ≥130（封顶）→ 途经任务点不再领（零边际，不浪费帧）。"""
        w = _joint_world(task=150, ice_nodes=["S03"], tasks=[_task("S03", 20, 3)])
        td, tf, ic, _ = sp._path_pickups(w, w.me, ["S01", "S03", "S05"])
        self.assertEqual(td, 0)      # 已封顶，不领
        self.assertEqual(tf, 0)
        self.assertEqual(ic, 1)      # ice 仍收集

    def test_project_route_credits_task_and_ice_along_path(self):
        """project_route 沿途建模：task_base += task_delta、deliver_frame 含领取/收集停靠帧。"""
        w = _joint_world(task=100, ice_nodes=["S03"], tasks=[_task("S03", 20, 3)])
        # 直送 [S01,S05] 无 task/ice；绕路 [S01,S03,S05] 经 S03
        p_direct = sp.project_route(w, w.me, self.gm, ["S01", "S05"], "S05", 0, self.ctx, 1.0)
        p_detour = sp.project_route(w, w.me, self.gm, ["S01", "S03", "S05"], "S05", 0, self.ctx, 1.0)
        self.assertEqual(p_direct["task_base"], 100)   # 直送无任务点
        self.assertEqual(p_detour["task_base"], 120)   # 100 + 20
        self.assertEqual(p_detour["task_delta"], 20)
        self.assertEqual(p_detour["ice_collected"], 1)
        # 绕路 deliver_frame 含 task(3) + ice(2) 停靠帧 + 路径帧差
        self.assertGreater(p_detour["deliver_frame"], p_direct["deliver_frame"])


class TestMultiMapAdaptivity(unittest.TestCase):
    """通用策略自适应性：冰源顺路图→改道（正向），冰源偏远图→保直送（中性，ΔEV 门拒绝）。"""

    def test_colocated_ice_task_route_picked(self):
        """冰源+任务点共址（S03 在鲜度绕路上）→ plan_route 改走绕路（联合 task+ice+鲜度收益）。

        这是 v1 分项式找不到、联合规划器能找到的"共址高效路线"。
        """
        ctx = GameContext(PID, "RED", 0, START_DATA)
        gm = ctx.game_map
        w = _joint_world(task=100, ice_nodes=["S03"], tasks=[_task("S03", 20, 3)])
        path, score = sp.plan_route(w, w.me, gm, "S01", "S05", "S05", ctx)
        self.assertEqual(path, ["S01", "S03", "S05"])  # 经共址冰源+任务点
        self.assertGreater(score, 0)

    def test_far_ice_route_refused(self):
        """冰源偏远（S03 绕路代价 >> 鲜度收益）、无任务点 → ΔEV 门拒绝，保时间最优直送。"""
        ctx = GameContext(PID, "RED", 0, FAR_ICE_MAP)
        gm = ctx.game_map
        w = _joint_world(task=100, ice_nodes=["S03"], tasks=[])  # 仅冰源，无任务
        path, _ = sp.plan_route(w, w.me, gm, "S01", "S05", "S05", ctx)
        self.assertEqual(path, ["S01", "S05"])  # 保直送，不为偏远冰源绕路

    def test_far_ice_with_task_still_picked(self):
        """偏远冰源但带任务点 → 任务 +20 收益 >> 绕路时间成本，仍改道（联合权衡：task 可补 ice 之短）。"""
        ctx = GameContext(PID, "RED", 0, FAR_ICE_MAP)
        gm = ctx.game_map
        w = _joint_world(task=100, ice_nodes=["S03"], tasks=[_task("S03", 20, 3)])
        path, _ = sp.plan_route(w, w.me, gm, "S01", "S05", "S05", ctx)
        self.assertEqual(path, ["S01", "S03", "S05"])  # 任务收益主导，仍绕路

    def test_adaptivity_same_planner_opposite_decisions(self):
        """同一规划器、同一输入（仅冰源 S03、无任务）在两张图上做出相反决策——证明拓扑自适应。

        顺路图（S03 绕路短、鲜度收益 > 时间成本）→ 改道；偏远图（绕路长、收益 < 成本）→ 保直送。
        决策完全由读 `start` 拓扑的 ΔEV 投影驱动，不依赖任何具体图——通用。
        """
        # 顺路图（START_DATA：S03 绕路短）→ 改道
        ctx_a = GameContext(PID, "RED", 0, START_DATA)
        w_a = _joint_world(task=100, ice_nodes=["S03"], tasks=[])
        path_a, _ = sp.plan_route(w_a, w_a.me, ctx_a.game_map, "S01", "S05", "S05", ctx_a)
        # 偏远图（FAR_ICE_MAP：S03 绕路长）→ 保直送
        ctx_b = GameContext(PID, "RED", 0, FAR_ICE_MAP)
        w_b = _joint_world(task=100, ice_nodes=["S03"], tasks=[])
        path_b, _ = sp.plan_route(w_b, w_b.me, ctx_b.game_map, "S01", "S05", "S05", ctx_b)
        self.assertEqual(path_a, ["S01", "S03", "S05"])
        self.assertEqual(path_b, ["S01", "S05"])
        self.assertNotEqual(path_a, path_b)  # 同输入不同图 → 不同决策（自适应）


if __name__ == "__main__":
    unittest.main()
