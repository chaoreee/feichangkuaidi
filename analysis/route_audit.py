"""Iter 35 §1 路线绕行归因（纯分析，零代码风险，不重跑）。

从 `reports/*.compact.log` 重建 me 实际访问节点序列，与 Dijkstra 最优路对比，
输出 Δ帧 / Δ鲜度损耗 + 绕行动机归因 + 净分 ROI 投影。复用 `core.rules`（帧/鲜度
公式）+ `core.pathfind`（Dijkstra）+ `analysis.compact.parse_compact`（还原 Report
取对手类与分项分）+ `analysis.opponent_classifier.classify_opponent`（对手类）。
纯 stdlib。

## 关键修正（Iter 34 勘误自身的勘误）

compact.log 中：
- `n=` = **me** 节点（client/main.py `node=` 字段）
- `on=` = **对手** 节点（client/main.py `oppNode=` 字段）

Iter 34 勘误（`docs/iter34_route_lever_analysis.md` §勘误）误把 `on=` 当作 me 途经
节点，得出 me 走 `S01→S02→S03→S06` 的错误路线（其中 S02/S03 实为对手节点）。实际
me 走 `S01→S06` 直连山路边（`S01-S06:44:M`）。本模块以 `n=` 重建 me 路线，`on=` 重建
对手路线（稀疏 ≤24 帧、低置信）。

## 方法论（对齐 Iter 34 §1.2）

- 帧数 `frames = ceil(ceil(distance × ROUTE_TIME_COEF[rt]) / 1000)`（= `rules.frames_on_edge`，base_move=1000、无天气）
- 鲜度损耗 `loss = frames × FRESHNESS_LOSS_MOVE[rt]`
- 仅计**移动损耗**（不含处理站/验核停靠/天气/急策），与 Iter 34 §1.2 同口径；
  实际/最优皆同口径故 Δ 公平，共享处理站（S13/S14）相消。
- 最优路 = Dijkstra 按"帧数"边权从 start→terminal（Iter 34 证三准则重合）。

## 输出

`reports/route_audit.json`（<100KB，经 sizeguard）：per-match 路线重建 + 按对手类聚合
（me 实际/最优路线偏差均值、绕行频率、Δ帧/Δ损耗、动机分布、ROI）。CLI：
`python3 -m analysis.route_audit <reports_dir>`。
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
from analysis.compact import parse_compact  # noqa: E402
from analysis.opponent_classifier import classify_opponent  # noqa: E402
from analysis.sizeguard import fit_text  # noqa: E402

# compact 路线类型字母 → rules 全名
_ROUTE_TYPE = {"R": "ROAD", "W": "WATER", "M": "MOUNTAIN", "B": "BRANCH"}

# 分数换算（与 Iter 34 §1.2 同口径）：鲜度分/freshness = 180/100 = 1.8；用时分/frame ≈ 70/600 = 0.117
_FRESHNESS_PER_POINT = 1.8
_TIME_PER_FRAME = 70.0 / 600.0


# --------------------------------------------------------------------------- #
# Map 解析（compact N/E 行 → 边表）                                            #
# --------------------------------------------------------------------------- #
class _Map:
    """轻量地图：节点集 + 边（from,to,distance,route_type,bidirectional）。"""

    def __init__(self, nodes_line, edges_line):
        self.nodes = []           # [(node_id, type_letter)]
        self.node_types = {}      # node_id -> type_letter
        for tok in nodes_line.split():
            if ":" in tok:
                nid, tletter = tok.split(":", 1)
                self.nodes.append((nid, tletter))
                self.node_types[nid] = tletter
            else:
                self.nodes.append((tok, ""))
        self.edges = []           # list of dict
        self._adj = {}            # node -> [(neighbor, distance, route_type)]
        for tok in edges_line.split():
            if ":" not in tok:
                continue
            head, dist, rletter = tok.split(":", 2)
            frm, to = head.split(">", 1) if ">" in head else head.split("-", 1)
            rt = _ROUTE_TYPE.get(rletter, "BRANCH")
            bidir = ">" not in head
            self.edges.append({"from": frm, "to": to, "distance": int(dist),
                               "route_type": rt, "bidirectional": bidir})
            self._adj.setdefault(frm, []).append((to, int(dist), rt))
            if bidir:
                self._adj.setdefault(to, []).append((frm, int(dist), rt))

    def edge(self, a, b):
        """a→b 相邻边的 (distance, route_type)；无则 None。"""
        for nb, d, rt in self._adj.get(a, ()):
            if nb == b:
                return d, rt
        return None

    def frame_adj(self):
        """Dijkstra 边权 = 单边帧数（rules.frames_on_edge, base_move=1000 无天气）。"""
        adj = {}
        for e in self.edges:
            w = rules.frames_on_edge(e["distance"], e["route_type"])
            adj.setdefault(e["from"], []).append((e["to"], w))
            if e["bidirectional"]:
                adj.setdefault(e["to"], []).append((e["from"], w))
        return adj

    def optimal_path(self, source, target):
        """帧数最优 (path, frames)；不可达 (None, inf)。"""
        return pathfind.shortest_path(self.frame_adj(), source, target)


# --------------------------------------------------------------------------- #
# compact.log 解析 → me/opp 路线 + 动作上下文                                  #
# --------------------------------------------------------------------------- #
def _parse_kv(tokens):
    d = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    return d


def _num(v):
    if v is None or v == "None":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        pass
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


class _MatchTrace:
    """单局 compact.log 累计器。"""

    def __init__(self):
        self.map = None              # _Map
        self.me_visits = []          # [(round, node)] me 实际到达节点（n= 变化）
        self.opp_visits = []         # [(round, node)] 对手节点（on= 变化）
        self.actions = []            # [{round, action, target, res, task, ...}]
        self.score_me = None
        self.score_opp = None
        self.match_id = None
        self.cur_node = None         # me 当前节点（CLAIM 上下文）
        self._first_node = None

    def feed_line(self, raw):
        line = raw.rstrip("\r")
        if not line.strip():
            return
        head = line.split(" ", 1)[0]
        rest = line[len(head):].strip()
        if head == "#":
            self.match_id = rest.split()[0] if rest else None
        elif head == "N":
            self._nodes_line = rest
        elif head == "E":
            mp = _Map(getattr(self, "_nodes_line", ""), rest)
            self.map = mp
        elif head == "F":
            self._on_frame(rest)
        elif head == "A":
            self._on_action(rest)
        elif head == "Score":
            self._on_score(rest)

    def _on_frame(self, rest):
        parts = rest.split()
        if not parts:
            return
        rnd = _num(parts[0][1:]) if parts[0].startswith("r") else None
        node = None
        onode = None
        for tok in parts[1:]:
            if tok.startswith("n="):
                node = tok[2:]
            elif tok.startswith("on="):
                onode = tok[3:]
        if node is not None:
            if self._first_node is None:
                self._first_node = node
            if not self.me_visits or self.me_visits[-1][1] != node:
                self.me_visits.append((rnd, node))
            self.cur_node = node
        if onode is not None:
            if not self.opp_visits or self.opp_visits[-1][1] != onode:
                self.opp_visits.append((rnd, onode))

    def _on_action(self, rest):
        parts = rest.split()
        if len(parts) < 2:
            return
        rnd = _num(parts[0][1:]) if parts[0].startswith("r") else None
        act = parts[1]
        kv = _parse_kv(parts[2:])
        rec = {"round": rnd, "action": act, "node": self.cur_node,
               "target": kv.get("target"), "res": kv.get("res"),
               "task": kv.get("task"), "fresh": _num(kv.get("fresh"))}
        self.actions.append(rec)

    def _on_score(self, rest):
        parts = rest.split()
        if not parts:
            return
        who = parts[0]
        kv = _parse_kv(parts[1:])
        score = {"total": _num(kv.get("total")) or 0,
                 "delivered": kv.get("del"),
                 "deliverRound": _num(kv.get("dframe")),
                 "fresh": _num(kv.get("fresh")),
                 "goodFruit": _num(kv.get("good")),
                 "taskScore": _num(kv.get("task")) or 0,
                 "bountyScore": _num(kv.get("bounty")) or 0}
        if who == "me":
            self.score_me = score
        else:
            self.score_opp = score


def parse_compact_match(text):
    """compact.log 文本 → _MatchTrace；无 Map/Score 返回 None。"""
    mt = _MatchTrace()
    for line in text.splitlines():
        mt.feed_line(line)
    if mt.map is None or mt.score_me is None:
        return None
    return mt


# --------------------------------------------------------------------------- #
# 路线核算                                                                      #
# --------------------------------------------------------------------------- #
def _leg_cost(mp, a, b):
    """a→b 单边 (frames, loss)；无直连边返回 None。"""
    e = mp.edge(a, b)
    if e is None:
        return None
    dist, rt = e
    fr = rules.frames_on_edge(dist, rt)
    loss = fr * rules.FRESHNESS_LOSS_MOVE[rt]
    return fr, loss


def reconstruct_route(mp, visits):
    """[(round,node)] → {path:[nodes], legs:[{from,to,dist,rt,frames,loss,round}],
    total_frames, total_loss, gaps:[(from,to)]}。

    gaps 为无直连边的跳变（理论上不应出现；出现则标注，路线帧/损耗不计入该跳）。
    """
    path = [v[1] for v in visits]
    legs = []
    total_frames = 0
    total_loss = 0.0
    gaps = []
    for i in range(len(visits) - 1):
        a, b = visits[i][1], visits[i + 1][1]
        if a == b:
            continue
        c = _leg_cost(mp, a, b)
        if c is None:
            gaps.append((a, b))
            continue
        fr, loss = c
        dist, rt = mp.edge(a, b)
        legs.append({"from": a, "to": b, "distance": dist, "route_type": rt,
                     "frames": fr, "loss": round(loss, 3), "round": visits[i + 1][0]})
        total_frames += fr
        total_loss += loss
    return {"path": path, "legs": legs, "total_frames": total_frames,
            "total_loss": round(total_loss, 3), "gaps": gaps}


def optimal_route(mp, source, target):
    """帧数最优路 + 沿途损耗。"""
    path, frames = mp.optimal_path(source, target)
    if path is None:
        return None
    loss = 0.0
    legs = []
    for i in range(len(path) - 1):
        c = _leg_cost(mp, path[i], path[i + 1])
        if c is None:
            continue
        fr, ls = c
        loss += ls
        legs.append({"from": path[i], "to": path[i + 1],
                     "frames": fr, "loss": round(ls, 3)})
    return {"path": path, "legs": legs, "total_frames": frames,
            "total_loss": round(loss, 3)}


def _off_optimal_nodes(actual_path, opt_path):
    """actual_path 中不在 opt_path 上的节点集合（绕行节点）。"""
    opt_set = set(opt_path or [])
    return [n for n in actual_path if n not in opt_set]


def attribute_detour(mt, actual, opt):
    """标注绕行动机：在 off-optimal 节点上 me 做了什么（领资源/领任务/清障/纯中转）。

    返回 {off_nodes:[{node,motive,resource,task}], resources_claimed, tasks_claimed,
    cleared}。motive ∈ {ICE_BOX, HORSE, TASK, CLEAR, TRANSIT}。
    """
    off_nodes = _off_optimal_nodes(actual["path"], opt["path"]) if opt else []
    off_set = set(off_nodes)
    per_node = {n: [] for n in off_nodes}
    for a in mt.actions:
        n = a.get("node")
        if n not in off_set:
            continue
        act = a.get("action")
        if act == "CLAIM_RESOURCE":
            res = a.get("res") or ""
            motive = "ICE_BOX" if "ICE" in res else "HORSE"
            per_node[n].append({"motive": motive, "resource": res})
        elif act == "CLAIM_TASK":
            per_node[n].append({"motive": "TASK", "task": a.get("task")})
        elif act in ("CLEAR", "SQUAD_CLEAR"):
            per_node[n].append({"motive": "CLEAR", "target": a.get("target")})
    # 汇总每个 off-node 的主导动机
    off_summary = []
    for n in off_nodes:
        acts = per_node[n]
        if not acts:
            off_summary.append({"node": n, "motive": "TRANSIT"})
            continue
        # 优先级 ICE_BOX > HORSE > TASK > CLEAR
        priority = {"ICE_BOX": 0, "HORSE": 1, "TASK": 2, "CLEAR": 3}
        primary = min(acts, key=lambda x: priority.get(x["motive"], 9))
        off_summary.append({"node": n, "motive": primary["motive"],
                            "acts": acts})
    resources = [a for a in mt.actions if a.get("action") == "CLAIM_RESOURCE"]
    tasks = [a for a in mt.actions if a.get("action") == "CLAIM_TASK"]
    cleared = [a for a in mt.actions if a.get("action") in ("CLEAR", "SQUAD_CLEAR")]
    return {"off_nodes": off_summary, "resources_claimed": resources,
            "tasks_claimed": tasks, "cleared": cleared}


def project_no_detour_score(mt, actual, opt, report):
    """投影"若走最优路、放弃绕行资源/任务"的终局分（rules.py 镜像，假设级）。

    compact Score 行 `task=` 字段 = task_base（原始累计，如 150），非任务分项（180）。
    假设（明确标注，非精确，仅供方向性参考）：
    1. 移动帧数 = opt.total_frames（放弃马；最优路上无资源节点则无马）。
    2. 移动鲜度损耗 = opt.total_loss；端鲜度 = 100 − opt.total_loss（放弃冰鉴；最优路上无冰源）。
       实际端鲜度含处理/天气额外损耗，故本投影为"纯路线"上界乐观估计（实际会更低）。
    3. 好果：按端鲜度是否跨 90/80 阈值估算（移动损耗单调下降，MIN = 端鲜度）。
    4. 任务分：放弃 off-optimal 节点上领取的任务；on-optimal 节点任务保留。
       task_base 按领任务数等比扣减（B × (N−off)/N，粗略）。
    5. 交付帧 = 实际交付帧 − 实际移动帧 + opt.total_frames（仅替换移动段，不扣 off-route 处理帧）。

    返回 {projected_total, actual_total, delta, ...}。
    """
    me = mt.score_me or {}
    actual_total = _num(me.get("total")) or 0
    if opt is None:
        return None
    opt_frames = opt["total_frames"]
    opt_loss = opt["total_loss"]
    # 端鲜度（无冰鉴）
    end_fresh = max(0.0, 100.0 - opt_loss)
    # 好果转坏：MIN = end_fresh（单调下降无冰鉴回升）
    bad = sum(1 for t in rules.GOOD_TO_BAD_THRESHOLDS if end_fresh < t)
    good_fruit = max(0, 100 - bad)
    # 任务分：扣 off-optimal 节点上的任务（按领任务数等比）
    off_set = set(_off_optimal_nodes(actual["path"], opt["path"]))
    actual_task_base = _num(me.get("taskScore")) or 0  # compact task= 即 task_base
    all_tasks = [a for a in mt.actions if a.get("action") == "CLAIM_TASK"]
    off_task_count = sum(1 for a in all_tasks if a.get("node") in off_set)
    n_tasks = len(all_tasks)
    if n_tasks > 0:
        proj_base = max(0, round(actual_task_base * (n_tasks - off_task_count) / n_tasks))
    else:
        proj_base = actual_task_base
    proj_task_score = rules.task_score(proj_base, delivered=True)
    # 交付帧
    actual_deliver = _num(me.get("deliverRound")) or 0
    actual_move = actual["total_frames"]
    proj_deliver = max(1, actual_deliver - actual_move + opt_frames)
    # 分项
    delivery = rules.delivery_base_score(proj_base)
    good = rules.good_fruit_score(good_fruit)
    fresh = rules.freshness_score(end_fresh)
    time_s = rules.time_score(proj_deliver, proj_base)
    bounty = _num(me.get("bountyScore")) or 0  # 绕行不涉悬赏，保留
    proj_total = rules.total_score([delivery, proj_task_score, time_s, good, fresh, bounty])
    return {
        "projected_total": proj_total,
        "actual_total": actual_total,
        "delta": round(proj_total - actual_total, 1),
        "proj_components": {"delivery": delivery, "task": proj_task_score,
                            "time": time_s, "goodFruit": good, "freshness": fresh,
                            "bounty": bounty},
        "proj_end_freshness": round(end_fresh, 2),
        "proj_good_fruit": good_fruit,
        "proj_deliver_frame": proj_deliver,
        "off_task_count": off_task_count,
        "assumptions": "optimal-route move frames/loss only; forfeit ice/horse/off-route tasks; "
                       "upper-bound optimistic (excludes processing/weather stall loss)",
    }


# --------------------------------------------------------------------------- #
# 单局归因                                                                      #
# --------------------------------------------------------------------------- #
def audit_match(text, opp_class=None):
    """compact.log 文本 → 单局归因 dict；解析失败返回 None。

    opp_class：可选， externally-supplied 对手类（优先取自 report.json 的
    classification.opponentClass，比从 compact 重分类更准——compact 不记 Guards 行，
    会欠检 guard-type）。未提供则回退到 parse_compact + classify_opponent。
    """
    mt = parse_compact_match(text)
    if mt is None or not mt.me_visits:
        return None
    mp = mt.map
    start = mt.me_visits[0][1]
    terminal = mt.me_visits[-1][1]
    actual = reconstruct_route(mp, mt.me_visits)
    opt = optimal_route(mp, start, terminal)
    detour = attribute_detour(mt, actual, opt)
    # 对手路线（稀疏、低置信）
    opp = None
    if mt.opp_visits:
        opp = reconstruct_route(mp, mt.opp_visits)
        opp["confidence"] = "low"  # ≤24 帧稀疏采样，仅 oppNode 变化点
    # Δ
    d_frames = actual["total_frames"] - (opt["total_frames"] if opt else 0)
    d_loss = round(actual["total_loss"] - (opt["total_loss"] if opt else 0), 3)
    # 分数换算
    d_loss_score = round(d_loss * _FRESHNESS_PER_POINT, 2)
    d_time_score = round(d_frames * _TIME_PER_FRAME, 2)
    # 对手类：优先外部提供（report.json），否则从 compact 回分类
    report = parse_compact(text)
    if opp_class is None:
        opp_class = (classify_opponent(report).get("class", "unknown")
                     if report is not None else "unknown")
    roi = project_no_detour_score(mt, actual, opt, report)
    return {
        "matchId": mt.match_id,
        "opponentClass": opp_class,
        "start": start,
        "terminal": terminal,
        "actual": actual,
        "optimal": opt,
        "delta": {"frames": d_frames, "loss": d_loss,
                  "loss_score": d_loss_score, "time_score": d_time_score},
        "detour": detour,
        "opponent_route": opp,
        "roi": roi,
        "score_me": mt.score_me,
    }


# --------------------------------------------------------------------------- #
# 聚合（按对手类）                                                              #
# --------------------------------------------------------------------------- #
def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def aggregate(audits):
    """按对手类聚合：实际/最优帧·损耗均值、绕行频率、Δ、动机分布、ROI。"""
    by_class = {}
    for a in audits:
        by_class.setdefault(a["opponentClass"], []).append(a)
    out = {}
    for cls, items in by_class.items():
        n = len(items)
        detoured = sum(1 for a in items if a["delta"]["loss"] > 0.5)
        out[cls] = {
            "N": n,
            "me_actual_frames": _mean([a["actual"]["total_frames"] for a in items]),
            "me_optimal_frames": _mean([a["optimal"]["total_frames"] if a["optimal"] else None for a in items]),
            "me_actual_loss": _mean([a["actual"]["total_loss"] for a in items]),
            "me_optimal_loss": _mean([a["optimal"]["total_loss"] if a["optimal"] else None for a in items]),
            "delta_frames": _mean([a["delta"]["frames"] for a in items]),
            "delta_loss": _mean([a["delta"]["loss"] for a in items]),
            "delta_loss_score": _mean([a["delta"]["loss_score"] for a in items]),
            "detour_freq": round(detoured / n, 3) if n else 0,
            "motive_dist": _motive_dist(items),
            "roi_delta_mean": _mean([a["roi"]["delta"] for a in items if a.get("roi")]),
            "me_mean_score": _mean([(a["score_me"] or {}).get("total") for a in items]),
        }
    return out


def _motive_dist(items):
    """各动机出现频次（按局计：一局有多种动机各计 1）。"""
    counts = {}
    for a in items:
        motives = set()
        for off in a["detour"]["off_nodes"]:
            motives.add(off["motive"])
        for m in motives:
            counts[m] = counts.get(m, 0) + 1
    return counts


def route_segment(audits, agg):
    """「## 路线绕行」段（markdown，供 reports/route_audit.md）。"""
    lines = ["## 路线绕行（Iter 35 §1，纯移动损耗口径，假设级）",
             "> me 实际路线 vs Dijkstra 帧数最优路（start→terminal）。Δ_loss 仅计移动损耗，",
             "> 不含处理/天气/急策；实际与最优同口径故 Δ 公平。N<30 标假设级。", ""]
    for cls in ("guard-type", "quality-route", "speed-route", "unknown"):
        a = agg.get(cls)
        if not a:
            continue
        lines.append(
            "  %-14s (N=%d): Δ帧=%s Δ损耗=%s(≈%s分) 绕行频率=%s "
            "实际帧=%s/最优帧=%s 动机=%s ROIΔ=%s"
            % (cls, a["N"], a["delta_frames"], a["delta_loss"],
               a["delta_loss_score"], a["detour_freq"], a["me_actual_frames"],
               a["me_optimal_frames"], a["motive_dist"], a["roi_delta_mean"]))
    lines.append("")
    lines.append("→ 归因：me 是否系统性绕行高损耗地形（山/支路）领资源/任务，"
                 "Δ损耗×1.8 与 ROIΔ 决定路线是否杠杆。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Iter 35 route detour audit from compact.log files.")
    ap.add_argument("reports_dir", help="directory containing *.compact.log")
    ap.add_argument("--out", default=None,
                    help="output json path (default <reports_dir>/route_audit.json)")
    args = ap.parse_args(argv)

    files = sorted(f for f in os.listdir(args.reports_dir)
                   if f.endswith(".compact.log"))
    # 预读 report.json 的对手类（compact 不记 Guards 行，重分类会欠检 guard-type）
    opp_class_map = {}
    for fn in files:
        rj = fn.replace(".compact.log", ".report.json")
        rpath = os.path.join(args.reports_dir, rj)
        if not os.path.isfile(rpath):
            continue
        try:
            with open(rpath, encoding="utf-8") as fh:
                rj_obj = json.load(fh)
        except (OSError, ValueError):
            continue
        mid = rj_obj.get("matchId")
        cls = (rj_obj.get("classification") or {}).get("opponentClass")
        if mid and cls:
            opp_class_map[mid] = cls
    audits = []
    skipped = 0
    for fn in files:
        path = os.path.join(args.reports_dir, fn)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        # 先 peek matchId 以查 opp_class_map
        mid_peek = None
        for line in text.splitlines():
            if line.startswith("# "):
                mid_peek = line.split()[1] if line.split() else None
                break
        a = audit_match(text, opp_class=opp_class_map.get(mid_peek))
        if a is None:
            skipped += 1
            continue
        audits.append(a)
    if not audits:
        print("no auditable compact.log in %s" % args.reports_dir, file=sys.stderr)
        return 1
    agg = aggregate(audits)
    segment = route_segment(audits, agg)
    out = {
        "n": len(audits),
        "skipped": skipped,
        "by_opponent_class": agg,
        "segment_md": segment,
        "matches": audits,
    }
    out_path = args.out or os.path.join(args.reports_dir, "route_audit.json")
    # sizeguard：超 100KB 则按 matches 头尾裁剪
    payload = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    if len(payload.encode("utf-8")) > 100_000:
        out["matches"] = _trim_matches(audits)
        payload = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(payload)
    print("audited %d matches (%d skipped) -> %s" % (len(audits), skipped, out_path))
    print(segment)
    # 同名 md 摘要
    md_path = out_path.replace(".json", ".md")
    if md_path == out_path:
        md_path = out_path + ".md"
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(fit_text("# Iter 35 路线绕行归因（N={n}）\n\n".format(n=len(audits)) + segment + "\n"))
    print("wrote %s" % md_path)
    return 0


def _trim_matches(audits):
    """超体积时仅保留每局摘要（去掉 legs/acts 细节）。"""
    slim = []
    for a in audits:
        slim.append({
            "matchId": a["matchId"],
            "opponentClass": a["opponentClass"],
            "actual_path": a["actual"]["path"],
            "optimal_path": a["optimal"]["path"] if a["optimal"] else None,
            "delta": a["delta"],
            "detour_motives": [o["motive"] for o in a["detour"]["off_nodes"]],
            "roi": a.get("roi"),
        })
    return slim


if __name__ == "__main__":
    sys.exit(main())
