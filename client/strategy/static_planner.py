"""Phase B 静态规划器（鲜度感知路线 + 冰鉴策略 + 终局分投影选择）。

见 docs/p0_attribution_batch2.md / docs/iteration_plan_v2.md §6。真实 30 局 trace 证伪
"任务"杠杆（task_base≥130 双双封顶 delivery 240 / task 180，多做任务零分）、确证"鲜度"为
真实杠杆（输局对手交付鲜度 90.6 vs 我 80.4 → freshness 分 +19；质量路线投影 +24）。本模块把
"早交付 vs 保鲜度"静态权衡当作优化问题求解：

- `freshness_optimal_path`：鲜度损耗最小的路径（Dijkstra，边权 = 逐边 `FRESHNESS_LOSS_MOVE ×
  frames_on_edge` + 途经处理站停靠损耗）。
- `project_route`：沿给定路径交付、用 k 次冰鉴的投影终局分（复用 `core/rules.py` + 鲜度模型）。
- `plan_route`：对候选路径（时间最优 / 鲜度最优）× 冰鉴用量 0..库存，取投影终局分最高者；仅当
  鲜度最优投影分高出时间最优 ≥ `STATIC_PLANNER_MIN_ROUTE_GAIN` 才改道，否则保时间最优。

冰鉴模型（对齐 sim/规则）：每次 `USE_RESOURCE(ICE_BOX)` +10 鲜度（封顶 100）、耗 1 动作帧
（推迟交付 1 帧）、可阻止 1 次 good→bad 阈值跨越（+10≈一个阈值带 90/80/…）。

默认关（`config.ENABLE_STATIC_PLANNER`）：baseline 行为不变。作 variant 仿真 A/B 验证
（N≥30 + 分段不回归）后才合入默认。纯函数 + 异常安全：任何错误回落时间最优路径，绝不抛出。
"""

import math

from core import pathfind, rules
from strategy.projection import freshness_loss_for_path, project_final_score

_INF = float("inf")
_ICE_RESTORE = 10.0          # 单次冰鉴鲜度恢复量（对齐 sim_engine / 规则）
_DEFAULT_VERIFY_FRAMES = 6   # gm 无 gate 信息时的回退


def _weather_coef(world):
    wtype = world.active_weather_type() if hasattr(world, "active_weather_type") else None
    if not wtype:
        return 1.0
    return rules.FRESHNESS_WEATHER_COEF.get(wtype, 1.0)


def _verify_frames(gm):
    if not gm.gate_node:
        return _DEFAULT_VERIFY_FRAMES
    info = gm.process_nodes.get(gm.gate_node)
    return (info.get("processRound") if info else _DEFAULT_VERIFY_FRAMES) or _DEFAULT_VERIFY_FRAMES


def _edge_freshness_loss(gm, a, b, weather_coef):
    """相邻 a→b 的鲜度损耗（移动帧损耗 + b 节点处理站停靠损耗，gate 除外）。不相邻返回 inf。"""
    e = gm.edge_between(a, b)
    if e is None:
        return _INF
    base = rules.FRESHNESS_LOSS_MOVE.get(e.route_type, rules.FRESHNESS_LOSS_BASE)
    fr = rules.frames_on_edge(e.distance, e.route_type)
    loss = fr * base * weather_coef
    if b != gm.gate_node and b in gm.process_nodes:
        loss += (gm.process_nodes[b].get("processRound") or 0) * rules.FRESHNESS_LOSS_BASE * weather_coef
    return loss


def freshness_optimal_path(gm, src, dst, blocked=None, weather_coef=1.0):
    """鲜度损耗最小的路径 (path, total_loss)。

    边权 = 逐边鲜度损耗（含目的节点处理站停靠），用 Dijkstra 求最小累计损耗。
    永不抛出：同点返回 ([src], 0.0)；不可达返回 ([], inf)。
    """
    blocked = frozenset(blocked or ())
    if src == dst:
        return ([src], 0.0)
    adj = {}
    for e in gm.edges:
        w = _edge_freshness_loss(gm, e.from_node, e.to_node, weather_coef)
        if e.to_node not in blocked and w != _INF:
            adj.setdefault(e.from_node, []).append((e.to_node, w))
        if e.bidirectional:
            w_ba = _edge_freshness_loss(gm, e.to_node, e.from_node, weather_coef)
            if e.from_node not in blocked and w_ba != _INF:
                adj.setdefault(e.to_node, []).append((e.from_node, w_ba))
    path, cost = pathfind.shortest_path(adj, src, dst)
    if path is None:
        return ([], _INF)
    return (path, cost)


def path_frames(gm, path, base_move=None):
    """路径总帧数（边移动 + 途经处理站读条；不含宫门验核，验核由调用方按 verified 加）。

    供 plan_route / 决策层做"绕行 vs 清障"代价比较。不可达（断边）返回 inf。
    """
    if not path or len(path) < 2:
        return 0
    bm = rules.BASE_MOVE_NONE if base_move is None else base_move
    total = 0
    for i in range(len(path) - 1):
        e = gm.edge_between(path[i], path[i + 1])
        if e is None:
            return _INF
        total += rules.frames_on_edge(e.distance, e.route_type, bm)
        mid = path[i + 1]
        if mid != gm.gate_node and mid in gm.process_nodes:
            total += (gm.process_nodes[mid].get("processRound") or 0)
    return total


def project_route(world, me, gm, path, terminal, ice_uses, ctx, weather_coef):
    """投影沿 path 交付、用 ice_uses 次冰鉴的终局分。

    返回 dict {score, deliver_frame, final_fresh, final_good, task_base, route_loss}，
    path 不可用 / 无法交付时返回 None。冰鉴模型见模块docstring。
    """
    if not path or len(path) < 2 or terminal is None:
        return None
    rnd = world.round or 0
    frames = path_frames(gm, path)
    if frames == _INF:
        return None
    verify = 0 if getattr(me, "verified", False) else _verify_frames(gm)
    deliver_frame = rnd + frames + verify + ice_uses      # 每次冰鉴耗 1 动作帧
    route_loss = freshness_loss_for_path(gm, path, weather_coef, verify_frames=verify)

    cur_fresh = me.freshness or 0.0
    fresh_no_ice = max(0.0, cur_fresh - route_loss)
    final_fresh = min(100.0, fresh_no_ice + _ICE_RESTORE * ice_uses)
    # 冰鉴补鲜度可阻止好果转坏阈值跨越：+10≈一个阈值带，每次抵 1 次 crossing。
    crossings_no_ice = len(rules.crossed_good_to_bad_thresholds(cur_fresh, fresh_no_ice))
    crossings = max(0, crossings_no_ice - ice_uses)
    final_good = max(0, (me.good_fruit or 0) - crossings)

    task_base = me.task_score or 0
    duration = ctx.duration_round or 600
    score = project_final_score(
        deliver_frame, task_base, final_good, final_fresh,
        penalty=me.penalty_score or 0, duration=duration)
    return {"score": score, "deliver_frame": deliver_frame,
            "final_fresh": final_fresh, "final_good": final_good,
            "task_base": task_base, "route_loss": route_loss}


def _best_score_for_path(world, me, gm, path, terminal, ctx, weather_coef, ice_budget):
    """单路径上遍历冰鉴用量 0..ice_budget 的最高投影分。返回 (score, k) 或 None。"""
    best = None
    for k in range(0, ice_budget + 1):
        proj = project_route(world, me, gm, path, terminal, k, ctx, weather_coef)
        if proj is None:
            continue
        if best is None or proj["score"] > best[0]:
            best = (proj["score"], k)
    return best


def plan_route(world, me, gm, src, dst, terminal, ctx, blocked=None):
    """选投影终局分最高的路线（时间最优 vs 鲜度最优 × 冰鉴用量 0..库存）。

    返回 (path, projected_score)。永不抛出：异常/不可达回落时间最优路径。
    仅当鲜度最优投影分高出时间最优 ≥ STATIC_PLANNER_MIN_ROUTE_GAIN 才改道，否则保时间最优
    （baseline 行为）——避免噪声驱动的微改道。

    冰鉴预算取 max(当前库存, STATIC_PLANNER_ICE_KEEP)：前瞻规划假设将收集到 KEEP 篓
    （由 _maybe_claim 按 STATIC_PLANNER_ICE_KEEP 落实），让路线选择看到质量路线的潜在收益。
    """
    import config
    blocked = frozenset(blocked or ())
    try:
        wcoef = _weather_coef(world)
        p_time, _ = gm.time_optimal_path(src, dst, blocked=blocked)
        p_fresh, _ = freshness_optimal_path(gm, src, dst, blocked, wcoef)

        candidates = []
        if p_time:
            candidates.append(p_time)
        if p_fresh and p_fresh != p_time:
            candidates.append(p_fresh)
        if not candidates:
            return (p_time or [], 0.0)

        ice_avail = 0
        if hasattr(me, "resource_count"):
            ice_avail = me.resource_count("ICE_BOX") or 0
        ice_budget = max(ice_avail, getattr(config, "STATIC_PLANNER_ICE_KEEP", 3))

        # 时间最优的最高分（对照基线）
        time_best = _best_score_for_path(world, me, gm, p_time, terminal, ctx, wcoef, ice_budget) \
            if p_time else None

        best = None  # (score, path)
        for path in candidates:
            scored = _best_score_for_path(world, me, gm, path, terminal, ctx, wcoef, ice_budget)
            if scored is None:
                continue
            if best is None or scored[0] > best[0]:
                best = (scored[0], path)

        if best is None:
            return (p_time or [], 0.0)

        # 改道门控：鲜度最优须高出时间最优 ≥ MIN_ROUTE_GAIN 才采用，否则保时间最优。
        best_path = best[1]
        if best_path != p_time and time_best is not None:
            if best[0] - time_best[0] < getattr(config, "STATIC_PLANNER_MIN_ROUTE_GAIN", 0.5):
                best_path = p_time
        return (best_path, best[0])
    except Exception:
        try:
            p, _ = gm.time_optimal_path(src, dst, blocked=blocked)
            return (p or [], 0.0)
        except Exception:
            return ([], 0.0)
