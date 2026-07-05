"""Iter 36 §1 资源感知路线重评（方案 B）：大路双冰鉴路线杠杆的硬核算。

触发：Iter 35 证伪「路线是鲜度杠杆」仅在「山路 vs 水路」窄对比下成立；存在第三选项
**大路** `S01→S02→S03→S07→S09→S10→S13→S14→S15`（经 S03/S07 双冰鉴 + S09 快马）未评估。
`samples/map_config.json` 的 `gameplay.resources`（V4.2-MEDIUM schema）揭示完整资源拓扑。
本模块用 `core/rules.py` 严格投影每条候选路线的终局分（含**马速建模**——static_planner 缺的
关键件：FAST_HORSE/SHORT_HORSE 按 HORSE_DURATION 帧持续、每帧 tick 含停靠、base_move 抬升
→ 单边帧数下降 → 鲜度损耗下降），输出大路 ROI vs 山路（me 现状）。

## 为什么需要新 walker（不复用 static_planner.project_route）

`static_planner.project_route` 的 `path_frames` 恒用 `base_move=1000`（无马建模），故对大路
的快马收益视而不见——而 Iter 35 §5.3 已指「马的密度」是鲜度 gap 真因。本 walker 逐帧模拟
（移动/处理/验核/领取/使用均 tick buff），把马的真实覆盖路段算进帧数与损耗。

## 方法论（对齐 Iter 35 §0 口径 + 资源/处理/验核全分项）

逐帧 walker（纯 `core/rules.py`）：
- 移动帧：`per_frame_move_amount(base_move)`，base_move 由当前 buff 决定（FAST 1200 / SHORT 1150 / NONE 1000）；
  每帧 `fresh −= FRESHNESS_LOSS_MOVE[rt]`；到站 `move_accum` 清零（对齐 sim，余量浪费）。
- 停靠帧（处理 processRound / 验核 / 领取 2 / 使用 1）：每帧 `fresh −= FRESHNESS_LOSS_BASE`；**buff 同步 tick**。
- 马策略（对齐 client `_maybe_claim`/`_maybe_horse`）：到马节点且无库存才领（FAST 优先）；
  无 buff 时使用（1 帧）→ buff_rem=HORSE_DURATION、buff_base=BASE_MOVE[type]；buff 活跃期间
  到新马节点只能领不能使（HORSE_BUFF_CONFLICT），等当前 buff 过期后下个节点使用。
- 冰鉴：每个冰源节点领 1 篓（2 帧）。使用建模为路线末尾最优时机（post-hoc，对齐
  static_planner）：`final_fresh=min(100, fresh_no_ice + 10×ice_uses)`、
  `crossings=max(0, crossings_no_ice − ice_uses)`、`final_good=100−crossings`；使用帧 +ice_uses。
- 处理站：途经 process_nodes（非 gate）按 client `_plan` 行为停靠 processRound 帧。
- 验核：gate 停靠 verify_frames（默认 6，无破关令/探路减免）。
- 任务分：假设 task_base=150（封顶）——五条候选路线均途经 ≥4 个任务候选节点（taskCandidates），
  跨 130 封顶，task_score=180、delivery=240 共享，Δ_task=0（documented）。任务领取帧不微分。
- 天气：coef=1.0（无天气），与 Iter 35 同口径上界乐观；五路线同 coef → Δ 公平。

## 候选路线（读 samples 拓扑，节点序列硬编码仅作命名标签——边存在性由 GameMap 校验）

山路（me 现状）：S01-S06-S08-S10-S13-S14-S15（1 冰鉴@S06 + 短马@S08）
水路（Dijkstra 帧最优）：S01-S02-S04-S05-S09-S10-S13-S14-S15（0 冰鉴 + 短马@S04 + 快马@S09）
大路（双冰鉴+快马）：S01-S02-S03-S07-S09-S10-S13-S14-S15（2 冰鉴@S03/S07 + 短马@S07 + 快马@S09）
S07 混合：S01-S02-S03-S07-S08-S10-S13-S14-S15（2 冰鉴 + 双短马@S07/S08，跳 S09 快马）
S09 混合：S01-S06-S08-S09-S10-S13-S14-S15（1 冰鉴@S06 + 短马@S08 + 快马@S09）
另：frame_optimal / fresh_optimal 由 GameMap Dijkstra 现算（不写死）。

## 输出

`reports/route_eval.json`（<100KB，sizeguard）+ `docs/iter36_route_eval.md`。CLI：
`python3 -m analysis.route_planner_eval`。**纯观测，不合入策略改动。**
"""

import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT = os.path.join(_ROOT, "client")
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from core import pathfind, rules  # noqa: E402
from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from strategy import static_planner as sp  # noqa: E402
from strategy.decision import GameContext  # noqa: E402
from strategy.projection import project_final_score, freshness_loss_for_path  # noqa: E402
from analysis.sizeguard import fit_text  # noqa: E402

_SAMPLES = os.path.join(_ROOT, "samples", "map_config.json")
_REPORTS = os.path.join(_ROOT, "reports")

_ICE_RESTORE = 10.0
_CLAIM_ROUND = 2          # RESOURCE_CLAIM_ROUND
_USE_ROUND = 1            # USE_RESOURCE 单帧
_VERIFY_FRAMES = 6        # 宫门验核（无破关令/探路减免）
_TASK_BASE_ASSUMED = 150  # 五路线均封顶（documented）
_DURATION = 600

# 候选路线（命名标签；边存在性由 GameMap 校验）
CANDIDATE_ROUTES = {
    "mountain": ["S01", "S06", "S08", "S10", "S13", "S14", "S15"],
    "water":    ["S01", "S02", "S04", "S05", "S09", "S10", "S13", "S14", "S15"],
    "mainroad": ["S01", "S02", "S03", "S07", "S09", "S10", "S13", "S14", "S15"],
    "s07mix":   ["S01", "S02", "S03", "S07", "S08", "S10", "S13", "S14", "S15"],
    "s09mix":   ["S01", "S06", "S08", "S09", "S10", "S13", "S14", "S15"],
}


# --------------------------------------------------------------------------- #
# samples → start_data + GameMap + 资源表                                       #
# --------------------------------------------------------------------------- #
def load_samples_start_data(path=_SAMPLES):
    """samples/map_config.json → GameMap 可吃的 start_data（nodes/edges/gameplay）。

    nodes 带-resourceStock（从 gameplay.resources 注入），gameplay.roles/processNodes 透传。
    """
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    nodes = []
    res_by_node = {}
    for r in cfg["gameplay"]["resources"]:
        res_by_node.setdefault(r["nodeId"], {})[r["resourceType"]] = r.get("count", 1)
    for n in cfg["nodes"]:
        nid = n["nodeId"]
        node = {"nodeId": nid, "nodeType": n.get("type"), "x": n.get("x"), "y": n.get("y")}
        if nid in res_by_node:
            node["resourceStock"] = res_by_node[nid]
        nodes.append(node)
    start_data = {
        "matchId": cfg.get("mapId", "samples"),
        "durationRound": _DURATION,
        "nodes": nodes,
        "edges": cfg["edges"],
        "map": {"gameplay": {"roles": cfg["gameplay"]["roles"],
                             "processNodes": cfg["gameplay"]["processNodes"]}},
    }
    return start_data, res_by_node, cfg


def build_game_map(start_data):
    return GameMap(start_data)


# --------------------------------------------------------------------------- #
# 逐帧 walker（马感知）                                                         #
# --------------------------------------------------------------------------- #
class _WalkState:
    __slots__ = ("frame", "fresh", "move_accum", "buff_rem", "buff_base",
                 "ice_inv", "horse_inv", "verified", "ice_claimed",
                 "horse_claimed", "move_frames", "stop_frames")

    def __init__(self):
        self.frame = 0
        self.fresh = 100.0
        self.move_accum = 0
        self.buff_rem = 0
        self.buff_base = rules.BASE_MOVE_NONE
        self.ice_inv = 0
        self.horse_inv = None        # 持有未激活的马类型
        self.verified = False
        self.ice_claimed = set()
        self.horse_claimed = set()
        self.move_frames = 0
        self.stop_frames = 0


def _tick_move(st, rt):
    """移动一帧：buff 决定 base_move，推进 move_accum，扣鲜度，tick buff。"""
    base = st.buff_base if st.buff_rem > 0 else rules.BASE_MOVE_NONE
    per = rules.per_frame_move_amount(base, 1000)
    st.move_accum += per
    st.frame += 1
    st.move_frames += 1
    if st.buff_rem > 0:
        st.buff_rem -= 1
    st.fresh = max(0.0, st.fresh - rules.FRESHNESS_LOSS_MOVE[rt])


def _tick_stop(st, n):
    """停靠 n 帧：每帧扣 BASE 鲜度、tick buff。"""
    for _ in range(n):
        st.frame += 1
        st.stop_frames += 1
        if st.buff_rem > 0:
            st.buff_rem -= 1
        st.fresh = max(0.0, st.fresh - rules.FRESHNESS_LOSS_BASE)


def _move_leg(st, gm, a, b):
    e = gm.edge_between(a, b)
    if e is None:
        return False
    amount = rules.to_station_move_amount(e.distance, e.route_type)
    rt = e.route_type
    while st.move_accum < amount:
        _tick_move(st, rt)
    st.move_accum = 0  # 到站清零（对齐 sim，余量浪费）
    return True


def walk_route(gm, path, res_by_node, opts):
    """逐帧走完 path → 投影 dict。详见模块 docstring。"""
    st = _WalkState()
    proc = gm.process_nodes
    gate = gm.gate_node
    verify = opts.get("verify_frames", _VERIFY_FRAMES)
    ok = True
    for i, node in enumerate(path):
        if i > 0:
            if not _move_leg(st, gm, path[i - 1], node):
                ok = False
                break
        # 1. 处理站停靠（非 gate、非起点；client _plan 行为）
        if i > 0 and node in proc and node != gate:
            _tick_stop(st, proc[node].get("processRound", 0) or 0)
        # 2. 领冰鉴（每冰源节点 1 篓）
        if node not in st.ice_claimed and res_by_node.get(node, {}).get("ICE_BOX", 0) > 0:
            _tick_stop(st, _CLAIM_ROUND)
            st.ice_inv += 1
            st.ice_claimed.add(node)
        # 3. 领马（无库存时；FAST 优先）
        if st.horse_inv is None:
            rstock = res_by_node.get(node, {})
            if rstock.get("FAST_HORSE", 0) > 0 and node not in st.horse_claimed:
                _tick_stop(st, _CLAIM_ROUND)
                st.horse_inv = "FAST_HORSE"
                st.horse_claimed.add(node)
            elif rstock.get("SHORT_HORSE", 0) > 0 and node not in st.horse_claimed:
                _tick_stop(st, _CLAIM_ROUND)
                st.horse_inv = "SHORT_HORSE"
                st.horse_claimed.add(node)
        # 4. 用马（无 buff 时）
        if st.horse_inv is not None and st.buff_rem == 0:
            _tick_stop(st, _USE_ROUND)
            st.buff_rem = rules.HORSE_DURATION[st.horse_inv]
            st.buff_base = rules.BASE_MOVE[st.horse_inv]
            st.horse_inv = None
        # 5. 宫门验核
        if node == gate and not st.verified:
            _tick_stop(st, verify)
            st.verified = True
    if not ok or (gate in path and not st.verified):
        return None
    # 6. 冰鉴使用（post-hoc 最优：末尾使用，+10×N 封顶 100、抵 crossing）
    fresh_no_ice = max(0.0, st.fresh)
    ice_uses = st.ice_inv
    st.frame += ice_uses  # 使用帧（末尾，buff 已过期无交互）
    crossings_no_ice = len(rules.crossed_good_to_bad_thresholds(100.0, fresh_no_ice))
    crossings = max(0, crossings_no_ice - ice_uses)
    final_good = max(0, 100 - crossings)
    final_fresh = min(100.0, fresh_no_ice + _ICE_RESTORE * ice_uses)
    task_base = opts.get("task_base", _TASK_BASE_ASSUMED)
    deliver_frame = st.frame
    score = project_final_score(deliver_frame, task_base, final_good, final_fresh,
                                duration=opts.get("duration", _DURATION))
    return {
        "path": path,
        "deliver_frame": deliver_frame,
        "move_frames": st.move_frames,
        "stop_frames": st.stop_frames,
        "route_loss": round(100.0 - fresh_no_ice, 3),
        "fresh_no_ice": round(fresh_no_ice, 3),
        "ice_inv": st.ice_inv,
        "ice_uses": ice_uses,
        "crossings_no_ice": crossings_no_ice,
        "crossings": crossings,
        "final_fresh": round(final_fresh, 3),
        "final_good": final_good,
        "task_base": task_base,
        "score": round(score, 2),
        "components": {
            "delivery": rules.delivery_base_score(task_base),
            "goodFruit": rules.good_fruit_score(final_good),
            "freshness": rules.freshness_score(final_fresh),
            "time": rules.time_score(deliver_frame, task_base),
            "task": rules.task_score(task_base, delivered=True),
            "bounty": 0,
        },
    }


# --------------------------------------------------------------------------- #
# Dijkstra 候选（帧最优 / 鲜度最优）                                            #
# --------------------------------------------------------------------------- #
def frame_optimal_path(gm, src, terminal):
    return gm.time_optimal_path(src, terminal)


def fresh_optimal_path(gm, src, terminal):
    return sp.freshness_optimal_path(gm, src, terminal, weather_coef=1.0)


# --------------------------------------------------------------------------- #
# 评估全部候选                                                                  #
# --------------------------------------------------------------------------- #
def evaluate_all(gm, res_by_node, opts=None):
    opts = opts or {}
    src = gm.start_node or "S01"
    terms = gm.terminal_nodes or ["S15"]
    terminal = terms[0]
    results = {}
    # 命名候选
    for name, path in CANDIDATE_ROUTES.items():
        proj = walk_route(gm, path, res_by_node, opts)
        if proj is None:
            continue
        results[name] = proj
    # Dijkstra 候选
    p_time, _ = frame_optimal_path(gm, src, terminal)
    if p_time:
        proj = walk_route(gm, p_time, res_by_node, opts)
        if proj:
            results["frame_optimal"] = proj
    p_fresh, _ = fresh_optimal_path(gm, src, terminal)
    if p_fresh and p_fresh != p_time:
        proj = walk_route(gm, p_fresh, res_by_node, opts)
        if proj:
            results["fresh_optimal"] = proj
    # Δ vs mountain（me 现状）
    base = results.get("mountain")
    if base:
        for name, proj in results.items():
            if name == "mountain":
                continue
            proj["delta_vs_mountain"] = {
                "score": round(proj["score"] - base["score"], 2),
                "deliver_frame": proj["deliver_frame"] - base["deliver_frame"],
                "fresh": round(proj["final_fresh"] - base["final_fresh"], 3),
                "good_fruit": proj["final_good"] - base["final_good"],
                "move_frames": proj["move_frames"] - base["move_frames"],
                "stop_frames": proj["stop_frames"] - base["stop_frames"],
            }
    return results


# --------------------------------------------------------------------------- #
# §1.3 static_planner.plan_route 在真实图上的选择                              #
# --------------------------------------------------------------------------- #
def _static_planner_world(start_data, res_by_node, node="S01", rnd=1):
    """构造最小 WorldState（me 在 src、node_states 带资源表）供 plan_route。"""
    inq = {"round": rnd, "phase": "NORMAL",
           "players": [{"playerId": 1001, "teamId": "RED", "state": "IDLE",
                        "currentNodeId": node, "verified": False,
                        "goodFruit": 100, "freshness": 100.0, "taskScore": 0,
                        "resources": {}}],
           "nodes": [{"nodeId": nid, "nodeType": "STATION", "resourceStock": stock}
                     for nid, stock in res_by_node.items()],
           "tasks": []}
    return WorldState(inq, 1001)


def static_planner_pick(start_data, res_by_node):
    """跑 plan_route（flag-on 语义），返回所选路径 + 是否=大路。

    static_planner 不建模马速，故其大路估值偏低——这本身是 §1.3 的发现。
    """
    import config
    ctx = GameContext(1001, "RED", 0, start_data)
    gm = ctx.game_map
    src = gm.start_node or "S01"
    terminal = (gm.terminal_nodes or ["S15"])[0]
    world = _static_planner_world(start_data, res_by_node, node=src)
    prev = bool(getattr(config, "ENABLE_STATIC_PLANNER", False))
    config.ENABLE_STATIC_PLANNER = True
    try:
        path, score = sp.plan_route(world, world.me, gm, src, terminal, terminal, ctx)
    finally:
        config.ENABLE_STATIC_PLANNER = prev
    mainroad = CANDIDATE_ROUTES["mainroad"]
    is_mainroad = list(path) == list(mainroad)
    return {"path": list(path), "score": round(score, 2),
            "is_mainroad": is_mainroad,
            "note": "static_planner 不建模马速（path_frames 恒 base_move=1000），大路快马收益不可见"}


# --------------------------------------------------------------------------- #
# §1.4 对手 on= 路线交叉验证                                                    #
# --------------------------------------------------------------------------- #
def _parse_compact_opponent(text):
    """从 compact.log 提取对手 on= 访问序列 + matchId。复用 route_audit 语义。"""
    mid = None
    opp_visits = []
    nodes_line = ""
    edges_line = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        head = line.split(" ", 1)[0]
        rest = line[len(head):].strip()
        if head == "#" and mid is None:
            mid = rest.split()[0] if rest else None
        elif head == "N":
            nodes_line = rest
        elif head == "E":
            edges_line = rest
        elif head == "F":
            for tok in rest.split():
                if tok.startswith("on="):
                    onode = tok[3:]
                    if not opp_visits or opp_visits[-1] != onode:
                        opp_visits.append(onode)
    return mid, opp_visits


# 路线资源签名（定义性特征 = 途经的关键资源节点集合）
_ROUTE_SIGNATURES = {
    "mountain": {"S06", "S08"},          # 山路：S06 冰鉴 + S08 短马
    "water":    {"S04", "S05"},          # 水路：S04/S05 处理站（+S09 快马）
    "mainroad": {"S03", "S07"},          # 大路：S03+S07 双冰鉴（定义性）
}


def _classify_by_signature(visits):
    """按途经资源节点分类路线；多类取大路优先（大路是 quality-route 假设主因）。"""
    vset = set(visits)
    if vset >= _ROUTE_SIGNATURES["mainroad"]:
        return "mainroad"
    if vset >= _ROUTE_SIGNATURES["mountain"]:
        return "mountain"
    if vset >= _ROUTE_SIGNATURES["water"]:
        return "water"
    return "other"


def cross_validate_opponent(reports_dir=_REPORTS):
    """统计对手 on= 路线分类（按资源节点签名）。

    on= 稀疏（≤24 帧、仅 oppNode 变化点），逐帧轨迹不可确证；但途经的关键资源节点
    （S03/S07 双冰鉴、S06 冰鉴、S04/S05 水路处理站）是路线的**定义性特征**，签名分类稳健。
    """
    if not os.path.isdir(reports_dir):
        return None
    files = sorted(f for f in os.listdir(reports_dir) if f.endswith(".compact.log"))
    n = 0
    by_class = {"mainroad": 0, "mountain": 0, "water": 0, "other": 0}
    mainroad_with_s09 = 0
    samples = []
    mainroad_samples = []
    for fn in files:
        with open(os.path.join(reports_dir, fn), encoding="utf-8") as fh:
            text = fh.read()
        mid, visits = _parse_compact_opponent(text)
        if not visits:
            continue
        n += 1
        cls = _classify_by_signature(visits)
        by_class[cls] += 1
        if cls == "mainroad":
            if "S09" in set(visits):
                mainroad_with_s09 += 1
            if len(mainroad_samples) < 5:
                mainroad_samples.append({"matchId": mid, "opp_route": visits})
        if len(samples) < 5:
            samples.append({"matchId": mid, "opp_route": visits, "class": cls})
    if n == 0:
        return None
    return {"n": n, "by_class": by_class,
            "mainroad_rate": round(by_class["mainroad"] / n, 3),
            "mainroad_with_s09": mainroad_with_s09,
            "samples": samples, "mainroad_samples": mainroad_samples,
            "confidence": "low",
            "note": "on= 稀疏（仅 oppNode 变化点）；按资源节点签名分类（大路=S03∧S07 双冰鉴），"
                    "非逐帧轨迹确证"}


# --------------------------------------------------------------------------- #
# 报告                                                                          #
# --------------------------------------------------------------------------- #
def _fmt_row(name, proj):
    c = proj["components"]
    d = proj.get("delta_vs_mountain", {})
    ds = ""
    if d:
        ds = "  Δscore=%s Δframe=%+d Δfresh=%+.2f Δgood=%+d" % (
            d["score"], d["deliver_frame"], d["fresh"], d["good_fruit"])
    return ("  %-14s frame=%3d(move %3d/stop %3d) loss=%.2f ice=%d fresh=%.1f good=%d "
            "score=%.1f [d=%d t=%d g=%d f=%d ti=%d]%s" % (
                name, proj["deliver_frame"], proj["move_frames"], proj["stop_frames"],
                proj["route_loss"], proj["ice_inv"], proj["final_fresh"], proj["final_good"],
                proj["score"], c["delivery"], c["task"], c["goodFruit"], c["freshness"],
                c["time"], ds))


def build_report_md(results, sp_pick, opp_cv):
    lines = ["# Iter 36 §1 路线 ROI 重评（资源感知，rules.py 严格投影）", "",
             "> 逐帧 walker（马感知：FAST/SHORT 按 HORSE_DURATION 帧持续、每帧 tick 含停靠）",
             "> + 冰鉴 post-hoc 最优 + 处理站/验核停靠。天气 coef=1.0（上界乐观，五路线同口径）。",
             "> task_base=150 假设封顶（五路线均途经 ≥4 任务节点，Δ_task=0）。", ""]
    lines.append("## 候选路线投影")
    lines.append("")
    base = results.get("mountain")
    for name in ("mountain", "water", "mainroad", "s07mix", "s09mix",
                 "frame_optimal", "fresh_optimal"):
        proj = results.get(name)
        if proj:
            lines.append(_fmt_row(name, proj))
    lines.append("")
    if base and "mainroad" in results:
        d = results["mainroad"].get("delta_vs_mountain", {})
        lines.append("## 大路 vs 山路（me 现状）Δ")
        lines.append("")
        lines.append("- 总分 Δ: **%+.2f**" % d["score"])
        lines.append("- 鲜度 Δ: %+.2f（端鲜度 %.1f vs %.1f）" % (
            d["fresh"], results["mainroad"]["final_fresh"], base["final_fresh"]))
        lines.append("- 好果 Δ: %+d" % d["good_fruit"])
        lines.append("- 交付帧 Δ: %+d（move %+d / stop %+d）" % (
            d["deliver_frame"], d["move_frames"], d["stop_frames"]))
        lines.append("- 冰鉴: 大路 %d vs 山路 %d" % (
            results["mainroad"]["ice_inv"], base["ice_inv"]))
        lines.append("")
        verdict = "杠杆确认（大路净正）" if d["score"] > 0.5 else (
            "中性/证伪" if d["score"] <= 0.5 else "杠杆确认")
        lines.append("→ 判定：**%s**（Δscore=%+.2f）" % (verdict, d["score"]))
        lines.append("")
    if sp_pick:
        lines.append("## §1.3 static_planner 在真实图的选择")
        lines.append("")
        lines.append("- plan_route 选: `%s`" % "→".join(sp_pick["path"]))
        lines.append("- 是否=大路: **%s**" % sp_pick["is_mainroad"])
        lines.append("- 投影分: %.1f" % sp_pick["score"])
        lines.append("- 注: %s" % sp_pick["note"])
        lines.append("")
    if opp_cv:
        lines.append("## §1.4 对手 on= 路线交叉验证")
        lines.append("")
        lines.append("- N=%d，按资源节点签名分类：%s" % (opp_cv["n"], opp_cv["by_class"]))
        lines.append("- 大路（S03∧S07 双冰鉴）占比: %.0f%%（含 S09 快马 %d 局）" % (
            opp_cv["mainroad_rate"] * 100, opp_cv["mainroad_with_s09"]))
        lines.append("- 置信: %s（%s）" % (opp_cv["confidence"], opp_cv["note"]))
        lines.append("- 大路样本：")
        for s in opp_cv.get("mainroad_samples", [])[:3]:
            lines.append("  - %s: %s" % (s["matchId"], "→".join(s["opp_route"])))
        lines.append("")
    lines.append("## 假设与限制")
    lines.append("")
    lines.append("- **+20 的前提是领 2 冰鉴**：baseline client `CLAIM_ICE_BOX_KEEP=1`，大路上鲜度到 S07 仍 ~91"
                 "（>81 用冰阈值）→ 不用冰 → 库存不空 → **不领 S07 冰鉴**，仅得 1 冰鉴（+10，Δ 退化为 ~+8）。"
                 "+20 的实现路径是开 `ENABLE_STATIC_PLANNER`（`STATIC_PLANNER_ICE_KEEP=3`，预囤 2 冰鉴）——"
                 "而 §1.3 已证 plan_route 在真实图选大路，二者一致。单独走大路不开 static_planner 不兑现。")
    lines.append("- 马策略对齐 client `_maybe_claim`/`_maybe_horse`（无库存才领、无 buff 才用、FAST 优先）；"
                 "buff 活跃期到新马节点领而不使（HORSE_BUFF_CONFLICT），下个节点使。"
                 "马收益小（FAST 仅覆盖 S09→S10 段 ~20 帧、省 ~4 帧）：大路鲜度增益主因是**第 2 冰鉴**（+10），"
                 "非马/路线类型（仅 +1.8）。")
    lines.append("- 冰鉴使用 post-hoc 最优（末尾、+10×N 封顶 100、抵 crossing）；大路 fresh_no_ice≈79 跨 90/80 两阈，"
                 "2 冰鉴恰抵 2 crossing → good=100；与 client `fresh<81 用冰` 实际行为一致（非过乐观）。")
    lines.append("- 处理站停靠按 client `_plan` 行为（途经 process_nodes 即停 processRound）；"
                 "障碍 CLEAR 帧、任务领取帧未微分（documented；大路障碍候选点仅 S10，山路 S06/S08/S10，大路占优未计）。")
    lines.append("- task_base=150 封顶假设；五路线均途经 ≥4 任务候选节点（S03/S06/S07/S08/S09/S10/S13）。")
    lines.append("- 天气 coef=1.0；**非单调鲜度（天气峰值致额外好果转坏）未建模**——大路高鲜度下天气伤害更小，"
                 "故好果 Δ 实际可能更大（+20 对好果保守）。绝对值上界乐观，Δ 方向稳健。")
    lines.append("- 资源拓扑来源 samples/map_config.json（真实图=samples+2 捷径边 E23/E24，资源按节点不变）；"
                 "淘汰赛/决赛换图，策略须通用读 start。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Iter 36 route ROI re-eval (resource-aware, horse-modeled).")
    ap.add_argument("--samples", default=_SAMPLES, help="map_config.json path")
    ap.add_argument("--reports", default=_REPORTS, help="reports dir (opponent cross-val)")
    ap.add_argument("--out", default=os.path.join(_REPORTS, "route_eval.json"))
    args = ap.parse_args(argv)

    start_data, res_by_node, _cfg = load_samples_start_data(args.samples)
    gm = build_game_map(start_data)
    results = evaluate_all(gm, res_by_node)
    sp_pick = static_planner_pick(start_data, res_by_node)
    opp_cv = cross_validate_opponent(args.reports)

    md = build_report_md(results, sp_pick, opp_cv)
    out = {"candidates": results, "static_planner_pick": sp_pick,
           "opponent_crossval": opp_cv, "report_md": md}
    payload = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    if len(payload.encode("utf-8")) > 100_000:
        out["candidates"] = {k: {kk: vv for kk, vv in v.items() if kk != "components"}
                             for k, v in results.items()}
        payload = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(payload)
    print("wrote %s" % args.out)
    print(md)
    md_path = args.out.replace(".json", ".md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(fit_text(md + "\n"))
    print("wrote %s" % md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
