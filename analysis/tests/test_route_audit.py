"""`analysis.route_audit` 单测——Iter 35 §1 路线绕行归因。

构造合成 compact.log（基于真实 quality-route 败局 Map 拓扑），验证：
1. me 路线重建正确（`n=` = me 节点，`on=` = 对手节点——Iter 34 勘误误读点）。
2. 最优路 Dijkstra 与 Iter 34 §1.2 手算一致（322 帧 / 16.98 损耗，水路 S04-S05-S09）。
3. me 实际路线帧/损耗手算一致（329 帧 / 21.875 损耗，山路 S01-S06-S08）。
4. Δ = +7 帧 / +4.895 损耗（非 Iter 34 勘误的 +64/+7.43）。
5. 绕行动机标注（S06=ICE_BOX, S08=HORSE）。
6. ROI 投影：放弃绕行后投影分 < 实际分（detour net gain > 0）。
7. 聚合 by_opponent_class 与 segment 渲染。
8. `on=` 不污染 me 路线（对手节点不入 me_visits）。
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # analysis 包可导入
sys.path.insert(0, os.path.join(_ROOT, "client"))

from analysis.route_audit import (  # noqa: E402
    _Map, audit_match, aggregate, route_segment, reconstruct_route, optimal_route,
    attribute_detour, project_no_detour_score, parse_compact_match,
)

# 真实 quality-route 败局 Map 拓扑（reports/ match_..._2696_vs_2986）
_NODES = ("S01:S S02:C S03:P S04:D S05:W S06:M S07:S S08:M S09:S S10:K "
          "S11:P S12:J S13:P S14:G S15:F")
_EDGES = ("S01-S02:30:R S02-S03:25:R S03-S07:54:R S07-S09:46:R S09-S10:40:R "
          "S10-S11:36:R S11-S12:20:R S12-S13:25:R S13-S14:18:R S14-S15:10:R "
          "S02-S04:20:R S04-S05:44:W S05-S07:46:B S01-S06:44:M S06-S08:54:M "
          "S08-S10:46:B S03-S06:38:B S05-S09:48:W S07-S08:42:M S04-S07:54:B "
          "S08-S09:64:B S11-S14:15:B S10-S13:27:B")

# 合成 compact.log（对齐真实 match_..._2696_vs_2986 关键行，省略无关 F 变化）
_COMPACT = """# match_test v=iter34 pid=2696 team=RED seed=None dur=600
Map N=15 E=23
N %(nodes)s
E %(edges)s
F r1 n=S01 st=IDLE ph=NORMAL gf=100 ts=0 on=S01 ots=0
A r1 CLEAR target=S06 fresh=100
A r1 SQUAD_CLEAR target=S08 fresh=100
A r7 MOVE target=S06 fresh=99.7
F r8 st=MOVING
F r43 on=S02
F r82 on=S03
F r86 n=S06 st=IDLE
A r86 CLAIM_RESOURCE target=S06 res=ICE_BOX fresh=94.1
A r86 SQUAD_CLEAR target=S10 fresh=94.1
A r88 MOVE target=S08 fresh=93.95
F r89 st=MOVING
F r162 on=S07
F r185 n=S08 st=IDLE
A r185 CLAIM_TASK task=T_003 fresh=85.08
A r189 CLAIM_TASK task=T_005 fresh=84.88
A r193 CLAIM_TASK task=T_009 fresh=84.68
A r197 CLAIM_RESOURCE target=S08 res=SHORT_HORSE fresh=84.48
A r199 MOVE target=S10 fresh=84.38
F r200 st=MOVING
A r200 USE_RESOURCE res=SHORT_HORSE fresh=84.32
F r236 on=S09
F r269 n=S10 st=IDLE
A r269 CLAIM_TASK task=T_008 fresh=80.18
A r273 CLAIM_TASK task=T_011 fresh=79.98
A r277 MOVE target=S13 fresh=79.78
F r278 st=MOVING
F r319 n=S13 st=IDLE
A r319 USE_RESOURCE res=ICE_BOX fresh=77.26
A r325 MOVE target=S14 fresh=86.96
F r326 st=MOVING
F r350 n=S14 st=IDLE
A r397 MOVE target=S15 fresh=83.5
F r398 st=MOVING
F r411 n=S15 st=IDLE
A r411 DELIVER fresh=83.36
Traj fstart=100 fmin=77.26 fend=83.36 gstart=100 gend=97 onode=S15 ofend=96.21 ogend=99
Over result=NORMAL reason=ALL_DELIVERED round=436 winner=2986 iWon=False
Score me total=766 del=True dframe=411 fresh=83.36 good=97 task=150 bounty=0 det=[bounty=0|delivery=240|freshness=150|goodFruit=174|penalty=0|tasks=180|time=22|total=766]
Score opp total=790 del=True dframe=436 fresh=96.21 good=99 task=165 bounty=0 det=[bounty=0|delivery=240|freshness=173|goodFruit=178|penalty=0|tasks=180|time=19|total=790]
""" % {"nodes": _NODES, "edges": _EDGES}


class TestMapAndOptimal(unittest.TestCase):
    def test_optimal_path_matches_iter34(self):
        """最优路 = 水路 S01→S02→S04→S05→S09→S10→S13→S14→S15，322 帧 / 16.98 损耗。"""
        mp = _Map(_NODES, _EDGES)
        opt = optimal_route(mp, "S01", "S15")
        self.assertEqual(opt["path"],
                         ["S01", "S02", "S04", "S05", "S09", "S10", "S13", "S14", "S15"])
        self.assertEqual(opt["total_frames"], 322)
        self.assertAlmostEqual(opt["total_loss"], 16.98, places=2)

    def test_edge_lookup(self):
        mp = _Map(_NODES, _EDGES)
        self.assertEqual(mp.edge("S01", "S06"), (44, "MOUNTAIN"))
        self.assertEqual(mp.edge("S04", "S05"), (44, "WATER"))
        self.assertIsNone(mp.edge("S01", "S15"))  # 不相邻


class TestRouteReconstruction(unittest.TestCase):
    def test_me_route_uses_n_not_on(self):
        """me 路线取自 `n=`（S01→S06→S08→S10→S13→S14→S15），`on=`（S02/S03/S07/S09）
        为对手节点、不污染 me 路线——Iter 34 勘误误把 on= 当 me 途经节点。"""
        mt = parse_compact_match(_COMPACT)
        self.assertEqual([v[1] for v in mt.me_visits],
                         ["S01", "S06", "S08", "S10", "S13", "S14", "S15"])
        self.assertEqual([v[1] for v in mt.opp_visits],
                         ["S01", "S02", "S03", "S07", "S09"])

    def test_actual_route_frames_loss(self):
        """me 实际路线 329 帧 / 21.875 损耗（手算：79+97+72+42+25+14）。"""
        mt = parse_compact_match(_COMPACT)
        actual = reconstruct_route(mt.map, mt.me_visits)
        self.assertEqual(actual["total_frames"], 329)
        self.assertAlmostEqual(actual["total_loss"], 21.875, places=3)
        self.assertEqual(actual["gaps"], [])  # 所有跳变均有直连边
        # 首段 S01→S06 直连山路边（79 帧），非 Iter 34 勘误的 S01→S02→S03→S06
        self.assertEqual(actual["legs"][0]["from"], "S01")
        self.assertEqual(actual["legs"][0]["to"], "S06")
        self.assertEqual(actual["legs"][0]["frames"], 79)

    def test_delta_is_small_not_iter34_claim(self):
        """Δ = +7 帧 / +4.895 损耗，非 Iter 34 勘误宣称的 +64/+7.43。"""
        a = audit_match(_COMPACT, opp_class="quality-route")
        self.assertEqual(a["delta"]["frames"], 7)
        self.assertAlmostEqual(a["delta"]["loss"], 4.895, places=3)


class TestDetourAttribution(unittest.TestCase):
    def test_off_nodes_motives(self):
        """绕行节点 S06=ICE_BOX、S08=HORSE（S08 亦有 TASK，但 HORSE 优先级高）。"""
        a = audit_match(_COMPACT, opp_class="quality-route")
        off = {o["node"]: o["motive"] for o in a["detour"]["off_nodes"]}
        self.assertEqual(off.get("S06"), "ICE_BOX")
        self.assertEqual(off.get("S08"), "HORSE")
        # S10/S13/S14/S15 在最优路上、不计为 off-node
        self.assertNotIn("S10", off)

    def test_resources_and_tasks_collected(self):
        a = audit_match(_COMPACT, opp_class="quality-route")
        res = [r["res"] for r in a["detour"]["resources_claimed"]]
        self.assertIn("ICE_BOX", res)
        self.assertIn("SHORT_HORSE", res)
        self.assertEqual(len(a["detour"]["tasks_claimed"]), 5)


class TestROI(unittest.TestCase):
    def test_detour_is_net_positive(self):
        """放弃绕行（无冰鉴/马/off-route 任务）投影分 < 实际分 → detour net gain > 0。"""
        a = audit_match(_COMPACT, opp_class="quality-route")
        roi = a["roi"]
        self.assertIsNotNone(roi)
        self.assertLess(roi["projected_total"], roi["actual_total"])
        self.assertGreater(roi["actual_total"] - roi["projected_total"], 100)
        # off-route 任务数 = 3（S08 的 T_003/T_005/T_009）
        self.assertEqual(roi["off_task_count"], 3)

    def test_proj_end_freshness_no_ice(self):
        """无冰鉴投影端鲜度 = 100 − opt_loss = 83.02。"""
        a = audit_match(_COMPACT, opp_class="quality-route")
        self.assertAlmostEqual(a["roi"]["proj_end_freshness"], 83.02, places=2)


class TestAggregate(unittest.TestCase):
    def test_aggregate_and_segment(self):
        a = audit_match(_COMPACT, opp_class="quality-route")
        agg = aggregate([a, a])
        qr = agg["quality-route"]
        self.assertEqual(qr["N"], 2)
        self.assertEqual(qr["detour_freq"], 1.0)
        self.assertAlmostEqual(qr["delta_loss"], 4.895, places=3)
        seg = route_segment([a, a], agg)
        self.assertIn("路线绕行", seg)
        self.assertIn("quality-route", seg)


class TestOpponentRouteConfidence(unittest.TestCase):
    def test_opponent_route_low_confidence(self):
        """对手路线从 `on=` 重建，标 low 置信。"""
        a = audit_match(_COMPACT, opp_class="quality-route")
        self.assertIsNotNone(a["opponent_route"])
        self.assertEqual(a["opponent_route"]["confidence"], "low")
        self.assertEqual(a["opponent_route"]["path"][0], "S01")


if __name__ == "__main__":
    unittest.main()
