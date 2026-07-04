"""Phase B 联合静态规划器（路线 × task × ice 一体投影选择）。

见 docs/p0_attribution_batch2.md / docs/iteration_plan_v2.md §6 / docs/calibration_v1.md。
真实 30 局 trace 证伪"任务"杠杆（task_base≥130 双封顶 delivery 240 / task 180，多做任务零分）、
确证"鲜度"为真实杠杆（+19/局）。v1 分项式（路线选择 / ice 绕路 / task 绕路各自为政）未过 A/B：
task 与 ice 争同一 spare-time 预算（零和），且 project_route 把 task_base 冻结、无法评估
"绕冰源 vs 绕任务点"的取舍。本版改为**联合**求解：

- `freshness_optimal_path`：鲜度损耗最小的路径（Dijkstra，边权 = 逐边损耗 + 途经处理站停靠）。
- `_path_pickups`：沿给定路径可领取的 task（贪心到 130 封顶）+ 可收集的 ice 概算——让路线
  选择能正确权衡"绕冰源多收 ice"与"绕任务点多做 task"的零和（v1 缺的关键）。
- `project_route`：沿路径交付、用 k 次冰鉴的投影终局分（复用 `core/rules.py` + 鲜度模型 +
  `_path_pickups` 的 task/ice 建模）。自动计入沿途 task 领取帧、ice 收集帧及其鲜度损耗。
- `plan_route`：候选 = 时间最优 + 鲜度最优 + 经冰源/任务点 waypoint 的拼接路线；每候选用
  `project_route`（× ice 用量 0..库存+沿途可收）投影终局分取最高，仅当同时过绝对增益门
  （≥ `STATIC_PLANNER_MIN_ROUTE_GAIN`）与每帧效率门（gain/extra ≥ `STATIC_PLANNER_MIN_ROUTE_EFFICIENCY`）
  才改道。读 `start` 拓扑动态生成候选，不写死节点（通用）。

冰鉴模型（对齐 sim/规则）：每次 `USE_RESOURCE(ICE_BOX)` +10 鲜度（封顶 100）、耗 1 动作帧
（推迟交付 1 帧）、可阻止 1 次 good→bad 阈值跨越。默认关（`config.ENABLE_STATIC_PLANNER`）：
baseline 行为不变。纯函数 + 异常安全：任何错误回落时间最优路径，绝不抛出。
"""

import math

from core import pathfind, rules
from strategy.projection import freshness_loss_for_path, project_final_score

_INF = float("inf")
_ICE_RESTORE = 10.0          # 单次冰鉴鲜度恢复量（对齐 sim_engine / 规则）
_ICE_CLAIM_FRAMES = 2        # 收集 1 篓冰鉴的读条帧（对齐 config.RESOURCE_CLAIM_ROUND）
_TASK_CAP = 130              # task_score 封顶的 task_base 阈值；过此多做任务零边际（rules）
_DEFAULT_VERIFY_FRAMES = 6   # gm 无 gate 信息时的回退
_WAYPOINT_MAX_EXTRA = 80     # waypoint 绕路允许的最大额外帧（防候选爆炸；ΔEV 门才是真正过滤器）
_EFFICIENCY_MIN_EXTRA = 15   # 每帧效率门仅对 extra≥此值的长绕路生效：短绕路时间成本估计可信，仅绝对增益门把关


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


def _best_task_at(world, nid):
    """节点 nid 上可领取的最高分任务 (score, processRound)；无可用任务返回 None。"""
    best = None
    for t in getattr(world, "tasks", []) or []:
        if t.get("nodeId") != nid:
            continue
        if not t.get("active") or t.get("completed") or t.get("failed"):
            continue
        sc = t.get("score") or 0
        pr = t.get("processRound") or 0
        if best is None or sc > best[0]:
            best = (sc, pr)
    return best


def _path_pickups(world, me, path):
    """沿 path 可领取的 task / 可收集的 ice 概算（用于路线终局分投影与对比）。

    返回 (task_delta, task_claim_frames, ice_collected, ice_claim_frames)：
    - task：每个途经任务节点领 1 个最高分任务，贪心到 task_base 达 _TASK_CAP(130) 封顶
      （过此多做任务零边际，不浪费帧）。
    - ice：每个途经有库存的冰源 +1 篓（每篓 _ICE_CLAIM_FRAMES 收集帧）。
    每节点只计一次（防 path 重访）。属投影近似——实际领取/收集由 _maybe_task / _maybe_claim
    在到达该节点时落地；此处仅为路线**对比**提供一致的潜在收益估算。
    """
    task_delta = 0
    task_frames = 0
    ice_collected = 0
    ice_frames = 0
    cur_tb = me.task_score or 0
    seen = set()
    node_states = getattr(world, "node_states", {}) or {}
    for nid in path:
        if nid in seen:
            continue
        seen.add(nid)
        # task：未到封顶时领取本节点最高分任务
        if cur_tb + task_delta < _TASK_CAP:
            bt = _best_task_at(world, nid)
            if bt is not None:
                task_delta += bt[0]
                task_frames += bt[1]
        # ice：有库存的冰源 +1 篓
        ns = node_states.get(nid)
        if ns is not None and ns.resource_available("ICE_BOX"):
            ice_collected += 1
            ice_frames += _ICE_CLAIM_FRAMES
    return task_delta, task_frames, ice_collected, ice_frames


def project_route(world, me, gm, path, terminal, ice_uses, ctx, weather_coef):
    """投影沿 path 交付、用 ice_uses 次冰鉴的终局分（含沿途 task/ice 建模）。

    自动计入 `_path_pickups`：沿途 task 领取（task_base += task_delta，+领取帧）、
    ice 收集（+收集帧，计入可用量上限）、领取/收集停靠帧的鲜度损耗。
    返回 dict {score, deliver_frame, final_fresh, final_good, task_base, route_loss,
              ice_collected, task_delta}；path 不可用 / 无法交付时返回 None。
    冰鉴模型见模块 docstring。
    """
    if not path or len(path) < 2 or terminal is None:
        return None
    rnd = world.round or 0
    frames = path_frames(gm, path)
    if frames == _INF:
        return None
    verify = 0 if getattr(me, "verified", False) else _verify_frames(gm)
    task_delta, task_frames, ice_collected, ice_frames = _path_pickups(world, me, path)
    stop_frames = task_frames + ice_frames
    deliver_frame = rnd + frames + verify + ice_uses + stop_frames      # 冰鉴使用 + 任务/冰鉴收集停靠
    route_loss = freshness_loss_for_path(gm, path, weather_coef, verify_frames=verify) \
                 + stop_frames * rules.FRESHNESS_LOSS_BASE * weather_coef

    cur_fresh = me.freshness or 0.0
    fresh_no_ice = max(0.0, cur_fresh - route_loss)
    final_fresh = min(100.0, fresh_no_ice + _ICE_RESTORE * ice_uses)
    # 冰鉴补鲜度可阻止好果转坏阈值跨越：+10≈一个阈值带，每次抵 1 次 crossing。
    crossings_no_ice = len(rules.crossed_good_to_bad_thresholds(cur_fresh, fresh_no_ice))
    crossings = max(0, crossings_no_ice - ice_uses)
    final_good = max(0, (me.good_fruit or 0) - crossings)

    task_base = (me.task_score or 0) + task_delta
    duration = ctx.duration_round or 600
    score = project_final_score(
        deliver_frame, task_base, final_good, final_fresh,
        penalty=me.penalty_score or 0, duration=duration)
    return {"score": score, "deliver_frame": deliver_frame,
            "final_fresh": final_fresh, "final_good": final_good,
            "task_base": task_base, "route_loss": route_loss,
            "ice_collected": ice_collected, "task_delta": task_delta}


def _best_score_for_path(world, me, gm, path, terminal, ctx, weather_coef):
    """单路径上遍历冰鉴用量 0..(库存 + 沿途可收) 的最高投影分。返回 (score, k, deliver_frame) 或 None。

    ice 预算 = 当前库存 + `_path_pickups` 沿途可收集量（前瞻规划假设将收集到）。
    透传最优 k 对应的 deliver_frame 供 plan_route 的每帧效率门计算真实总时间成本。
    """
    inv = 0
    if hasattr(me, "resource_count"):
        inv = me.resource_count("ICE_BOX") or 0
    probe = project_route(world, me, gm, path, terminal, 0, ctx, weather_coef)
    if probe is None:
        return None
    ice_budget = inv + probe.get("ice_collected", 0)
    best = (probe["score"], 0, probe["deliver_frame"])
    for k in range(1, ice_budget + 1):
        proj = project_route(world, me, gm, path, terminal, k, ctx, weather_coef)
        if proj is None:
            continue
        if proj["score"] > best[0]:
            best = (proj["score"], k, proj["deliver_frame"])
    return best


def _via_path(gm, src, waypoints, terminal, blocked):
    """src → w1 → ... → terminal 的拼接时间最短路。

    返回 (path, frames)。拒绝**非简单路径**（含重复节点/回溯段）：waypoint 间最短路若绕回
    src 或已访问节点，拼接后会形成回环，逐帧重规划时导致在回环处振荡卡死（真实败局模式）。
    任一段不可达或拼接后非简单路径 → 返回 (None, inf)。
    """
    nodes = [src] + list(waypoints) + [terminal]
    full = []
    total = 0
    for i in range(len(nodes) - 1):
        seg, c = gm.time_optimal_path(nodes[i], nodes[i + 1], blocked=blocked)
        if not seg or c == _INF:
            return None, _INF
        total += c
        full.extend(seg if i == 0 else seg[1:])   # 后续段去掉与前段重复的衔接点
    # 简单性校验：含重复节点（回溯/回环）的候选直接丢弃
    if len(set(full)) != len(full):
        return None, _INF
    return full, total


def _build_candidates(world, me, gm, src, terminal, blocked, p_time, p_fresh):
    """生成候选路线集：时间最优 + 鲜度最优 + 经冰源/任务点 waypoint 的拼接路线。

    读 `start` 拓扑动态枚举（不写死节点）：冰源取 world.node_states 中有 ICE_BOX 库存者；
    任务点取 world.tasks 中 active 未完成者。waypoint 绕路额外帧 ≤ _WAYPOINT_MAX_EXTRA 才入选
    （防候选爆炸；真正过滤由 plan_route 的 ΔEV 门负责）。含 (ice, task) 二段组合以覆盖
    "冰源与任务点共址"的高效路线（真实对手 fresh 93 + task 165 共存所暗示）。
    """
    candidates = []
    if p_time:
        candidates.append(p_time)
    if p_fresh and p_fresh != p_time:
        candidates.append(p_fresh)

    direct = path_frames(gm, p_time) if p_time else _INF

    ice_nodes = []
    for nid, ns in (getattr(world, "node_states", {}) or {}).items():
        if nid in (src, terminal):
            continue
        if ns.resource_available("ICE_BOX"):
            ice_nodes.append(nid)

    task_nodes = []
    for t in getattr(world, "tasks", []) or []:
        if not t.get("active") or t.get("completed") or t.get("failed"):
            continue
        nid = t.get("nodeId")
        if nid and nid not in (src, terminal) and nid not in task_nodes:
            task_nodes.append(nid)

    # 单 waypoint：经 1 个冰源 或 1 个任务点
    for w in ice_nodes + task_nodes:
        p, c = _via_path(gm, src, [w], terminal, blocked)
        if p is None or c - direct > _WAYPOINT_MAX_EXTRA:
            continue
        candidates.append(p)

    # 二段组合：(冰源, 任务点)——覆盖冰源/任务共址路线
    for i in ice_nodes:
        for t in task_nodes:
            if i == t:
                continue
            p, c = _via_path(gm, src, [i, t], terminal, blocked)
            if p is None or c - direct > _WAYPOINT_MAX_EXTRA:
                continue
            candidates.append(p)

    return candidates


def plan_route(world, me, gm, src, dst, terminal, ctx, blocked=None):
    """选投影终局分最高的**完整交付路线**（联合 task/ice/freshness/time）。

    flag-on 时规划 src→terminal 的完整交付路线（`dst` 仅保留签名兼容，作异常回落目标）：
    候选 = 时间最优 + 鲜度最优 + 经冰源/任务点 waypoint 的拼接路线（`_build_candidates`）。
    每候选用 `project_route`（自动建模沿途 task 领取 + ice 收集 + ice 用量 0..预算）投影终局分，
    取最高；仅当高出时间最优 ≥ `STATIC_PLANNER_MIN_ROUTE_GAIN` 才改道，否则保时间最优。
    永不抛出：异常/不可达回落时间最优路径。
    """
    import config
    blocked = frozenset(blocked or ())
    try:
        if terminal is None:
            p, _ = gm.time_optimal_path(src, dst, blocked=blocked)
            return (p or [], 0.0)
        wcoef = _weather_coef(world)
        p_time, _ = gm.time_optimal_path(src, terminal, blocked=blocked)
        p_fresh, _ = freshness_optimal_path(gm, src, terminal, blocked, wcoef)

        candidates = _build_candidates(world, me, gm, src, terminal, blocked, p_time, p_fresh)

        # 去重
        seen = set()
        uniq = []
        for p in candidates:
            key = tuple(p)
            if key and key not in seen:
                seen.add(key)
                uniq.append(p)
        if not uniq:
            return (p_time or [], 0.0)

        time_best = _best_score_for_path(world, me, gm, p_time, terminal, ctx, wcoef) \
            if p_time else None

        best = None  # (score, path, deliver_frame)
        for path in uniq:
            scored = _best_score_for_path(world, me, gm, path, terminal, ctx, wcoef)
            if scored is None:
                continue
            if best is None or scored[0] > best[0]:
                best = (scored[0], path, scored[2])
        if best is None:
            return (p_time or [], 0.0)

        # ΔEV 改道门控：候选须同时过 (1) 绝对增益门 gain ≥ MIN_ROUTE_GAIN 与
        # (2) 每帧效率门 gain/extra ≥ MIN_ROUTE_EFFICIENCY 才采用，否则保时间最优。
        # 效率门仅对长绕路（extra ≥ _EFFICIENCY_MIN_EXTRA）生效：吸收投影对长绕路时间成本的
        # 系统性乐观（暴雨/山雾减速未建模、未来天气隐藏）——拒 +7/+60=0.12/帧 的低效长绕路，
        # 纳 +7/+10=0.7/帧 的高效绕路。短绕路时间成本估计可信，仅绝对增益门把关。
        best_path = best[1]
        if best_path != p_time and time_best is not None:
            gain = best[0] - time_best[0]
            extra = best[2] - time_best[2]   # 总交付帧差（移动+停靠+验核+冰鉴使用）
            min_gain = getattr(config, "STATIC_PLANNER_MIN_ROUTE_GAIN", 0.5)
            min_eff = getattr(config, "STATIC_PLANNER_MIN_ROUTE_EFFICIENCY", 0.3)
            if gain < min_gain or (extra >= _EFFICIENCY_MIN_EXTRA and gain / extra < min_eff):
                best_path = p_time
        return (best_path, best[0])
    except Exception:
        try:
            p, _ = gm.time_optimal_path(src, dst, blocked=blocked)
            return (p or [], 0.0)
        except Exception:
            return ([], 0.0)
