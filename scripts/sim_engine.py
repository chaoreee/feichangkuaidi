"""高保真自博弈物理引擎（Phase A）——进程内、纯 stdlib、物理一律调 client/core/rules.py。

设计原则（docs/iteration_plan_v2.md §5）：仿真器物理 = 我们的规则镜像。移动/鲜度/
天气/设卡/得分公式全部调用 ``client/core/rules.py``，不重写。唯一无法内部验证的是
"规则镜像是否 = 平台真实规则"，由 Phase 0 真实 trace 兜底。所有结论标
"sim-only，待真实 trace 验证"。

本模块只做物理推进 + inquire 构造，不含决策引擎（由 sim_server 编排真实 DecisionEngine）。
动作结算口径对齐任务书：移动按路线距离×耗时系数（§2.3.2）、鲜度逐帧损耗+阈值转坏（§3.2）、
天气 4 次×60 帧+提前 30 预告（§2.5）、探路标记 45 帧可用+处理/验核 -3（§6.4.1）、
宫门验核 6 帧（§252）、RUSH 触发四条件+450 强制（§6.5）、路线边空动作 park WAITING（Iter8）。

Phase A 范围（标"待完善"）：悬赏/窗口争夺留空（client 相关 ENABLE_* 默认关，baseline 不触发）；
动态资源刷新不做（仅 visibleResources 一次性）；任务池 seed 合成（非平台真实任务池）；
天气作用区域近似为按路线类型匹配（HOT 全图；暴雨命中水路；山雾命中山路）。
"""

import math
import random

from core import rules
from protocol.enums import Phase, PlayerState, Team


# ---- 任务书常量（非 rules.py 镜像的补充口径）----

WEATHER_DURATION = 60            # 每次天气持续帧数（§2.5）
WEATHER_FORECAST = 30            # 提前预告帧数（§2.5）
WEATHER_START_RANGES = [(80, 120), (200, 240), (320, 360), (440, 480)]  # 4 次天气起始帧范围
WEATHER_TYPES = ("HOT", "HEAVY_RAIN", "MOUNTAIN_FOG")

SCOUT_MARK_TTL = 45              # 探路标记可用帧数（§6.4.1：生成帧 X 可用到 X+45）
PROCESS_SCOUT_REDUCE = 3         # 探路标记处理减时（§6.4.1，最低 2）
VERIFY_BASE_FRAMES = 6           # 宫门验核基础帧数（§252）
VERIFY_BREAK_ORDER_REDUCE = 3    # 破关令验核减时（最低 3，§6.5）
VERIFY_SCOUT_REDUCE = 3          # 探路标记验核减时（最低 2，§6.4.1）
CLEAR_FRAMES = 8                 # 主动清障帧数（= OBSTACLE_TIME_TAX，plan 指定）
CLAIM_RESOURCE_FRAMES = 2        # 领取资源帧数
SQUAD_DELAY = 3                  # 小分队延迟落地帧数
SQUAD_SCOUT_COST = 1             # SQUAD_SCOUT 人手
SQUAD_CLEAR_COST = 2             # SQUAD_CLEAR 人手
SQUAD_OTHER_COST = 2             # SQUAD_WEAKEN/REINFORCE 人手
REST_AFTER_BREAK_FAIL = 5        # 攻坚失败休整帧数（§6.3.1）
GUARD_SETUP_FRAMES = 4           # 设卡处理帧数（GUARD_SETUP_FRAMES-1 处理 + 1 激活）
INITIAL_SQUAD = 8                # 初始小分队人手
INITIAL_GUARD_AP = 4             # 初始护卫行动点

# RUSH 触发窗口（§6.5）
RUSH_WINDOW_START = 390
RUSH_WINDOW_END = 449
RUSH_FORCE_FRAME = 450
RUSH_GATE_DIST_LE = 15           # 到 S14 最短路线距离阈值
RUSH_REACH_S15_FRAMES = 60       # 基础最快可达 S15 帧数阈值

# 障碍候选点（均有绕行可能，避免堵死唯一通路 S13→S14）
OBSTACLE_CANDIDATES = ("S06", "S08", "S11")

# 节点类型 → 设卡 node_kind（rules.guard_time_tax 用）
def _guard_kind(node_type, is_gate, has_obstacle):
    if has_obstacle:
        return "obstacle_node"
    if is_gate:
        return "gate"
    if node_type == "KEY_PASS":
        return "key_pass"
    return "normal"


class _Player:
    """单玩家运行期状态。"""

    def __init__(self, player_id, team_id, camp, start_node):
        self.player_id = player_id
        self.team_id = team_id
        self.camp = camp
        self.pos = start_node
        self.next_node = None
        self.route_edge = None        # Edge 对象
        self.move_accum = 0           # 当前边累计移动量
        self.state = PlayerState.IDLE
        self.freshness = 100.0
        self.good_fruit = 100
        self.bad_fruit = 0
        self.frozen_good_fruit = 0
        self.verified = False
        self.delivered = False
        self.deliver_round = 0
        self.retired = False
        self.resources = {}           # resourceType -> count
        self.buffs = []               # [{"type", "remaining"}]
        self.squad_available = INITIAL_SQUAD
        self.guard_action_point = INITIAL_GUARD_AP
        self.rush_tactic_used = 0
        self.task_score = 0
        self.bounty_score = 0
        self.penalty_score = 0
        self.missing_action_rounds = 0
        self.illegal_action_count = 0
        self.current_process = None   # {"node","type","remaining","ctx"}
        self.processed_nodes = set()  # 已完成固定处理的节点
        self.rest_remaining = 0       # 休整倒计时

    # ---- buff 查询 ----

    def active_move_buff(self):
        for b in self.buffs:
            if b["type"] in ("FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"):
                return b["type"]
        return None

    def base_move(self):
        b = self.active_move_buff()
        return rules.BASE_MOVE.get(b, rules.BASE_MOVE_NONE)

    def has_buff(self, btype):
        return any(b["type"] == btype for b in self.buffs)

    def resource_count(self, rtype):
        return self.resources.get(rtype, 0)


class SimEngine:
    """双玩家自博弈物理引擎。

    用法：``eng = SimEngine(start_data, game_map, seed)``；每帧
    ``eng.step({"RED": actions, "BLUE": actions})`` 推进，随后
    ``eng.build_inquire(team)`` 取该队视角的 inquire_data 喂给 DecisionEngine。
    """

    def __init__(self, start_data, game_map, seed):
        self.start_data = start_data
        self.game_map = game_map
        self.seed = seed
        self.rng = random.Random(seed)

        self.match_id = start_data.get("matchId")
        self.duration_round = start_data.get("durationRound") or 600
        self.round = 0
        self.phase = Phase.NORMAL

        start_node = game_map.start_node or "S01"
        self.gate = game_map.gate_node
        self.terminals = game_map.terminal_nodes or ["S15"]
        self.terminal = self.terminals[0]

        # 双玩家（playerId 与 start_data.players 对齐）
        pl = start_data.get("players") or []
        red = next((p for p in pl if p.get("teamId") == Team.RED), pl[0] if pl else {})
        blue = next((p for p in pl if p.get("teamId") == Team.BLUE), pl[1] if len(pl) > 1 else {})
        self.players = {
            Team.RED: _Player(red.get("playerId", 1001), Team.RED, red.get("camp", 0), start_node),
            Team.BLUE: _Player(blue.get("playerId", 2001), Team.BLUE, blue.get("camp", 1), start_node),
        }
        self.team_of_pid = {p.player_id: t for t, p in self.players.items()}

        # 节点状态
        self.node_types = {n.node_id: n.type for n in game_map.nodes.values()}
        self.resource_stock = {}      # nodeId -> {rtype: count}
        for r in (start_data.get("resources") or []):
            self.resource_stock.setdefault(r["nodeId"], {})
            self.resource_stock[r["nodeId"]][r["resourceType"]] = self.resource_stock[r["nodeId"]].get(r["resourceType"], 0) + (r.get("count", 1) or 1)
        self.obstacles = {}           # nodeId -> {"type"}
        self.guards = {}              # nodeId -> {"owner","defense","active"}
        self.scout_marks = {}         # nodeId -> [{"team","expire"}]

        # 任务实例（seed 合成；标"任务池待真实 trace 对齐"）
        self.tasks = self._synth_tasks()

        # 天气排期（seed 定起始帧与类型；标"待真实 trace 校准"）
        self.weather_schedule = self._synth_weather()

        # 延迟落地的小分队
        self.pending_squad = []       # [{"arrive","node","team","kind"}]

        # 本帧事件 + 上帧 actionResult（喂下帧 inquire）
        self.events = []
        self.action_results = []

    # ---- 初始化辅助 ----

    def _synth_tasks(self):
        """seed 合成任务实例。按真实平台 11 局 trace 校准（reports/，N=11 假设级 §3.7）：

        真实观察：TASK_90_REACH=1.00、双方 task_base 均 120-150（mean 144.5）、任务出现在
        最短路沿途站点 S06/S08/S10/S11/S12/S13（S01→S06→S08→S10→S11→S12→S13→S14→S15）、
        单节点可领多个任务（实局 S10 连领 T_006/T_008/T_010/T_011/T_013）。旧版仅 3 个共享
        任务 ×30=90（总量 90 双方分），TASK_90_REACH=0.04，严重偏离。

        本版：12 个任务分布 6 个沿途站点（每站 2 个）、score 15、processRound 3-4，
        **每玩家独立完成追踪**（completed_by 集合）——双方各可累计到 ~130（task 分封顶 180
        时边际归零自动停止），对齐真实双玩家均达 90+。OBJECT_BUSY 仅在"本玩家重复领已完成
        任务"时触发（复现实局 CLAIM_TASK 重试风暴的拒绝语义）；跨玩家不互斥（实局双方各自
        高分亦支持非互斥）。仍标"假设级"：N=11<30，确切分值/每站数量/是否刷新待更多 trace。
        """
        stations = ["S06", "S08", "S10", "S11", "S12", "S13"]
        # 每站任务数（沿途 6 站共 10 个）；score 20 使客户端领 ~7 个即触 task 分封顶 180 停止
        # （边际归零门），对齐实局 base 120-150 且不过度停车推迟交付。
        per_station = [1, 1, 2, 2, 2, 2]
        tasks = []
        idx = 0
        for nid, k in zip(stations, per_station):
            for _ in range(k):
                idx += 1
                tasks.append({
                    "taskId": "TK%d" % idx,
                    "taskTemplateId": "T%02d" % idx,
                    "nodeId": nid,
                    "score": 20,
                    "processRound": 3,
                    "active": True, "failed": False,
                    "completed_by": set(),   # 每玩家独立完成追踪
                })
        return tasks

    def _synth_weather(self):
        """4 次天气，每次起始帧在其范围内 seed 选取，持续 60 帧，类型 seed 选取。"""
        sched = []
        for (lo, hi) in WEATHER_START_RANGES:
            start = self.rng.randint(lo, hi)
            wtype = self.rng.choice(WEATHER_TYPES)
            sched.append({"start": start, "end": start + WEATHER_DURATION - 1, "type": wtype})
        return sched

    def _place_obstacles(self):
        """seed 决定 0-1 个障碍（候选均有绕行）。在 step 首帧前调用。"""
        if self.rng.random() < 0.4:
            nid = self.rng.choice(OBSTACLE_CANDIDATES)
            self.obstacles[nid] = {"type": "ROCKFALL"}

    # ---- 天气 ----

    def _active_weather(self, rnd):
        for w in self.weather_schedule:
            if w["start"] <= rnd <= w["end"]:
                return w["type"]
        return None

    def _next_weather(self, rnd):
        for w in self.weather_schedule:
            if w["start"] > rnd and w["start"] - rnd <= WEATHER_FORECAST:
                return {"type": w["type"], "startIn": w["start"] - rnd}
        return None

    def _weather_move_mult(self, route_type, wtype):
        return rules.weather_move_multiplier(route_type, wtype) if wtype else 1000

    def _weather_fresh_coef(self, route_type, wtype):
        """鲜度天气系数：HOT 全图；暴雨仅水路；山雾仅山路（按路线类型近似作用区域）。"""
        if wtype is None:
            return 1.0
        if wtype == "HOT":
            return rules.FRESHNESS_WEATHER_COEF["HOT"]
        if wtype == "HEAVY_RAIN" and route_type == "WATER":
            return rules.FRESHNESS_WEATHER_COEF["HEAVY_RAIN"]
        if wtype == "MOUNTAIN_FOG" and route_type == "MOUNTAIN":
            return rules.FRESHNESS_WEATHER_COEF["MOUNTAIN_FOG"]
        return 1.0

    # ---- 探路标记 ----

    def _add_scout_mark(self, node, team, rnd):
        self.scout_marks.setdefault(node, []).append({"team": team, "expire": rnd + SCOUT_MARK_TTL})

    def _consume_scout_mark(self, node, team):
        """消费最早一个本队可用标记；返回是否消费成功（处理/验核减时用）。"""
        marks = self.scout_marks.get(node, [])
        for i, m in enumerate(marks):
            if m["team"] == team:
                del marks[i]
                return True
        return False

    def _clean_scout_marks(self, rnd):
        for nid in list(self.scout_marks.keys()):
            self.scout_marks[nid] = [m for m in self.scout_marks[nid] if m["expire"] >= rnd]
            if not self.scout_marks[nid]:
                del self.scout_marks[nid]

    # ---- 主推进 ----

    def step(self, actions_by_team):
        """推进一帧。actions_by_team: {team: [action, ...]}。"""
        self.round += 1
        rnd = self.round
        if rnd == 1:
            self._place_obstacles()
        self.events = []

        # 1) RUSH 触发判定（仅 NORMAL 态）
        if self.phase == Phase.NORMAL:
            self._maybe_trigger_rush(rnd)

        # 2) 处理/验核/清障/设卡/休整倒计时推进（在结算新动作前）
        for team, p in self.players.items():
            self._tick_processing(p, team, rnd)

        # 3) 落地延迟小分队
        self._deliver_pending_squad(rnd)

        # 4) 结算双方主车队动作（RED 先，BLUE 后；无物理碰撞，仅共享节点状态）
        self.action_results = []
        for team in (Team.RED, Team.BLUE):
            p = self.players[team]
            acts = actions_by_team.get(team, []) or []
            self._resolve_player(p, team, acts, rnd)

        # 5) 移动推进（MOVING 续行已在 _resolve_player 处理；此处补 buff/休整倒计时）
        for p in self.players.values():
            self._tick_buffs(p)
            if p.rest_remaining > 0:
                p.rest_remaining -= 1

        # 6) 鲜度结算 + 好→坏转换
        for team, p in self.players.items():
            self._settle_freshness(p, rnd)

        # 7) 设卡风化
        self._weather_guards()

        # 8) 探路标记清理
        self._clean_scout_marks(rnd)

        # 9) 结束判定
        if all(p.delivered or p.retired for p in self.players.values()) or rnd >= self.duration_round:
            self.phase = Phase.ENDED

    def _maybe_trigger_rush(self, rnd):
        if rnd < RUSH_WINDOW_START:
            return
        if rnd >= RUSH_FORCE_FRAME:
            self.phase = Phase.RUSH
            self.events.append({"type": "RUSH_START", "round": rnd})
            return
        if rnd > RUSH_WINDOW_END:
            return
        # 四条件任一满足
        for p in self.players.values():
            if p.delivered or p.retired:
                continue
            if p.pos == self.gate:  # 已到 S14
                self.phase = Phase.RUSH
                self.events.append({"type": "RUSH_START", "round": rnd})
                return
            if p.pos in ("S11", "S12", "S13"):
                continue
            dist = self.game_map.route_distance(p.pos, self.gate)
            if dist != math.inf and dist <= RUSH_GATE_DIST_LE:
                self.phase = Phase.RUSH
                self.events.append({"type": "RUSH_START", "round": rnd})
                return
            _, frames = self.game_map.time_optimal_path(p.pos, self.terminal)
            if frames != math.inf and frames <= RUSH_REACH_S15_FRAMES:
                self.phase = Phase.RUSH
                self.events.append({"type": "RUSH_START", "round": rnd})
                return

    # ---- 处理/验核/清障倒计时 ----

    def _tick_processing(self, p, team, rnd):
        cp = p.current_process
        if cp is None:
            return
        cp["remaining"] -= 1
        if cp["remaining"] > 0:
            return
        # 落地
        kind = cp["type"]
        node = cp["node"]
        p.current_process = None
        p.state = PlayerState.IDLE
        if kind == "PROCESS":
            p.processed_nodes.add(node)
            self.events.append({"type": "PROCESS_COMPLETE", "round": rnd, "payload": {"playerId": p.player_id, "nodeId": node}})
        elif kind == "VERIFY":
            p.verified = True
            self.events.append({"type": "VERIFY_GATE_COMPLETE", "round": rnd, "payload": {"playerId": p.player_id}})
        elif kind == "CLEAR":
            self.obstacles.pop(node, None)
            p.good_fruit = max(0, p.good_fruit - 1)
            self.events.append({"type": "OBSTACLE_CLEAR", "round": rnd, "payload": {"playerId": p.player_id, "nodeId": node}})
        elif kind == "CLAIM_RESOURCE":
            rtype = cp["ctx"]
            stock = self.resource_stock.get(node, {})
            if stock.get(rtype, 0) > 0:
                stock[rtype] -= 1
                p.resources[rtype] = p.resources.get(rtype, 0) + 1
            self.events.append({"type": "RESOURCE_CLAIM", "round": rnd, "payload": {"playerId": p.player_id, "nodeId": node, "resourceType": rtype}})
        elif kind == "CLAIM_TASK":
            tid = cp["ctx"]
            t = next((x for x in self.tasks if x["taskId"] == tid), None)
            if t and p.player_id not in t.get("completed_by", set()):
                t["completed_by"].add(p.player_id)
                p.task_score += t.get("score", 0)
            self.events.append({"type": "TASK_COMPLETE", "round": rnd, "payload": {"playerId": p.player_id, "taskId": tid, "taskScore": p.task_score}})
        elif kind == "SET_GUARD":
            extra = cp["ctx"].get("extra", 0)
            defense = rules.guard_defense(extra, 10)  # max_defense 上限 10（保守）
            self.guards[node] = {"owner": team, "defense": defense, "active": True}
            self.events.append({"type": "GUARD_SET", "round": rnd, "payload": {"playerId": p.player_id, "nodeId": node, "defense": defense}})
        elif kind == "FORCED_PASS":
            # 强制通行完成：付完时间税，移动到目标节点（不清除障碍/设卡，仅本次通过）
            if node != p.pos:
                p.pos = node
                self.events.append({"type": "NODE_ENTER", "round": rnd, "payload": {"playerId": p.player_id, "nodeId": p.pos}})

    def _deliver_pending_squad(self, rnd):
        still = []
        for s in self.pending_squad:
            if s["arrive"] <= rnd:
                node, team, kind = s["node"], s["team"], s["kind"]
                if kind == "SQUAD_SCOUT":
                    self._add_scout_mark(node, team, rnd)
                    self.events.append({"type": "SCOUT_MARKER_ADD", "round": rnd, "payload": {"nodeId": node, "teamId": team}})
                elif kind == "SQUAD_CLEAR":
                    self.obstacles.pop(node, None)
                    self.events.append({"type": "OBSTACLE_CLEAR", "round": rnd, "payload": {"byTeam": team, "nodeId": node}})
                elif kind == "SQUAD_WEAKEN":
                    g = self.guards.get(node)
                    if g and g["owner"] != team:
                        g["defense"] = max(0, g["defense"] - 2)
                elif kind == "SQUAD_REINFORCE":
                    g = self.guards.get(node)
                    if g and g["owner"] == team:
                        g["defense"] = min(10, g["defense"] + 2)
            else:
                still.append(s)
        self.pending_squad = still

    # ---- 动作结算 ----

    def _resolve_player(self, p, team, acts, rnd):
        main = next((a for a in acts if not str(a.get("action", "")).startswith("SQUAD_")), None)
        squad = next((a for a in acts if str(a.get("action", "")).startswith("SQUAD_")), None)

        # 休整中：只能 WAIT/空动作
        if p.rest_remaining > 0:
            if main is None or main.get("action") in (None, "WAIT"):
                self._result(p, rnd, main, accepted=True)
            else:
                self._result(p, rnd, main, accepted=False, code="RESTING_ACTION_FORBIDDEN")
            if squad:
                self._apply_squad(p, team, squad, rnd)
            return

        # 处理/验核/清障/设卡/强制通行中：不接新主动作（心跳/WAIT 放行）
        if p.current_process is not None:
            if main is None or main.get("action") in (None, "WAIT"):
                self._result(p, rnd, main, accepted=True)
            else:
                self._result(p, rnd, main, accepted=False, code="MOVING_ACTION_FORBIDDEN")
            if squad:
                self._apply_squad(p, team, squad, rnd)
            return

        # 已交付/退赛：不动作
        if p.delivered or p.retired:
            self._result(p, rnd, main, accepted=(main is None or main.get("action") in (None, "WAIT")))
            return

        act = main.get("action") if main else None

        # MOVING / WAITING 态：仅续行(MOVE 到当前 nextNode)或用马前进；否则 park WAITING（Iter8）
        if p.state in (PlayerState.MOVING, PlayerState.WAITING):
            if act == "USE_RESOURCE" and main.get("resourceType") in ("FAST_HORSE", "SHORT_HORSE"):
                self._use_resource(p, team, main, rnd)
                self._advance_move(p, team, rnd)
            elif act == "MOVE" and main.get("targetNodeId") == p.next_node:
                self._advance_move(p, team, rnd)
            elif act == "MOVE" and main.get("targetNodeId") == p.pos:
                # 已在节点却被报 WAITING（无在途目标）→ 不前进，保持等待（client 会重规划）
                self._result(p, rnd, main, accepted=True)
            else:
                p.state = PlayerState.WAITING
                self._result(p, rnd, main, accepted=(act in (None, "WAIT")))
            if squad:
                self._apply_squad(p, team, squad, rnd)
            return

        # IDLE 态：接新动作
        if p.state != PlayerState.IDLE:
            self._result(p, rnd, main, accepted=False, code="MOVING_ACTION_FORBIDDEN")
            return

        self._apply_idle(p, team, main, act, rnd)
        if squad:
            self._apply_squad(p, team, squad, rnd)

    def _apply_idle(self, p, team, main, act, rnd):
        if act in (None, "WAIT"):
            self._result(p, rnd, main, accepted=True)
            return
        if act == "MOVE":
            self._start_move(p, team, main, rnd)
        elif act == "PROCESS":
            self._start_process(p, team, main, rnd)
        elif act == "VERIFY_GATE":
            self._start_verify(p, team, main, rnd)
        elif act == "CLEAR":
            self._start_clear(p, team, main, rnd)
        elif act == "CLAIM_RESOURCE":
            self._start_claim_resource(p, team, main, rnd)
        elif act == "CLAIM_TASK":
            self._start_claim_task(p, team, main, rnd)
        elif act == "USE_RESOURCE":
            self._use_resource(p, team, main, rnd)
        elif act == "RUSH_PROTECT":
            self._rush_protect(p, team, main, rnd)
        elif act == "RUSH_SPEED":
            self._rush_speed(p, team, main, rnd)
        elif act == "SET_GUARD":
            self._start_set_guard(p, team, main, rnd)
        elif act == "BREAK_GUARD":
            self._break_guard(p, team, main, rnd)
        elif act == "FORCED_PASS":
            self._forced_pass(p, team, main, rnd)
        elif act == "DELIVER":
            self._deliver(p, team, main, rnd)
        elif act == "DOCK":
            self._start_process(p, team, main, rnd)  # DOCK 等同处理（Phase A 简化）
        elif act == "WINDOW_CARD":
            self._result(p, rnd, main, accepted=False, code="OBJECT_BUSY")  # Phase A 无窗口
        else:
            self._result(p, rnd, main, accepted=False, code="INVALID_ACTION_TYPE")

    # ---- 移动 ----

    def _start_move(self, p, team, main, rnd):
        tgt = main.get("targetNodeId")
        if tgt is None:
            self._result(p, rnd, main, accepted=False, code="PARAM_OUT_OF_RANGE")
            return
        if tgt == p.pos:
            self._result(p, rnd, main, accepted=True)
            return
        edge = self.game_map.edge_between(p.pos, tgt)
        if edge is None:
            self._result(p, rnd, main, accepted=False, code="MOVE_EDGE_NOT_FOUND")
            return
        # 障碍 / 敌方有效设卡阻断
        blocked = self._node_blocked_for(tgt, team)
        if blocked:
            self._result(p, rnd, main, accepted=False, code="MOVE_BLOCKED_BY_GUARD")
            return
        p.next_node = tgt
        p.route_edge = edge
        p.move_accum = 0
        p.state = PlayerState.MOVING
        self._result(p, rnd, main, accepted=True)
        # advance-on-start：本帧即开始推进
        self._advance_move(p, team, rnd)

    def _node_blocked_for(self, node, team):
        if node in self.obstacles:
            return True
        g = self.guards.get(node)
        if g and g["active"] and g["defense"] > 0 and g["owner"] != team:
            return True
        return False

    def _advance_move(self, p, team, rnd):
        if p.state not in (PlayerState.MOVING, PlayerState.WAITING) or p.route_edge is None:
            return
        p.state = PlayerState.MOVING
        edge = p.route_edge
        wtype = self._active_weather(rnd)
        wmult = self._weather_move_mult(edge.route_type, wtype)
        per = rules.per_frame_move_amount(p.base_move(), wmult)
        p.move_accum += per
        need = rules.to_station_move_amount(edge.distance, edge.route_type)
        if p.move_accum >= need:
            p.pos = p.next_node
            p.next_node = None
            p.route_edge = None
            p.move_accum = 0
            p.state = PlayerState.IDLE
            self.events.append({"type": "NODE_ENTER", "round": rnd, "payload": {"playerId": p.player_id, "nodeId": p.pos}})

    # ---- 处理 / 验核 / 清障 / 领取 / 任务 ----

    def _start_process(self, p, team, main, rnd):
        node = main.get("targetNodeId") or p.pos
        if node != p.pos:
            self._result(p, rnd, main, accepted=False, code="NOT_AT_TARGET_NODE")
            return
        info = self.game_map.process_nodes.get(node)
        if not info or node == self.gate:
            self._result(p, rnd, main, accepted=False, code="PROCESS_NOT_AVAILABLE")
            return
        if node in p.processed_nodes:
            self._result(p, rnd, main, accepted=False, code="PROCESS_NOT_AVAILABLE")
            return
        frames = info.get("processRound", 0) or 0
        frames = self._maybe_scout_reduce(p, team, node, frames, 2)
        p.current_process = {"node": node, "type": "PROCESS", "remaining": frames, "ctx": None}
        p.state = PlayerState.PROCESSING
        self._result(p, rnd, main, accepted=True)

    def _start_verify(self, p, team, main, rnd):
        if p.pos != self.gate:
            self._result(p, rnd, main, accepted=False, code="NOT_AT_TARGET_NODE")
            return
        if self.phase != Phase.RUSH:
            self._result(p, rnd, main, accepted=False, code="PROCESS_NOT_AVAILABLE")
            return
        if p.verified:
            self._result(p, rnd, main, accepted=False, code="ALREADY_VERIFIED")
            return
        frames = VERIFY_BASE_FRAMES
        break_order = main.get("rushTactic") == "BREAK_ORDER"
        if break_order and p.rush_tactic_used == 0:
            frames = max(3, frames - VERIFY_BREAK_ORDER_REDUCE)
            p.rush_tactic_used += 1
        else:
            frames = self._maybe_scout_reduce(p, team, self.gate, frames, 2)
        p.current_process = {"node": self.gate, "type": "VERIFY", "remaining": frames, "ctx": None}
        p.state = PlayerState.VERIFYING
        self._result(p, rnd, main, accepted=True)

    def _maybe_scout_reduce(self, p, team, node, frames, minimum):
        if self._consume_scout_mark(node, team):
            return max(minimum, frames - PROCESS_SCOUT_REDUCE)
        return frames

    def _start_clear(self, p, team, main, rnd):
        tgt = main.get("targetNodeId") or p.pos
        if tgt not in self.obstacles:
            self._result(p, rnd, main, accepted=False, code="OBSTACLE_NOT_FOUND")
            return
        if tgt != p.pos and tgt not in self.game_map.neighbors(p.pos):
            self._result(p, rnd, main, accepted=False, code="NOT_AT_TARGET_NODE")
            return
        frames = CLEAR_FRAMES
        frames = self._maybe_scout_reduce(p, team, tgt, frames, 2)
        p.current_process = {"node": tgt, "type": "CLEAR", "remaining": frames, "ctx": None}
        p.state = PlayerState.PROCESSING
        self._result(p, rnd, main, accepted=True)

    def _start_claim_resource(self, p, team, main, rnd):
        node = main.get("targetNodeId") or p.pos
        rtype = main.get("resourceType")
        if node != p.pos:
            self._result(p, rnd, main, accepted=False, code="NOT_AT_TARGET_NODE")
            return
        if not rtype or (self.resource_stock.get(node, {}).get(rtype, 0) or 0) <= 0:
            self._result(p, rnd, main, accepted=False, code="RESOURCE_NOT_AVAILABLE")
            return
        p.current_process = {"node": node, "type": "CLAIM_RESOURCE", "remaining": CLAIM_RESOURCE_FRAMES, "ctx": rtype}
        p.state = PlayerState.PROCESSING
        self._result(p, rnd, main, accepted=True)

    def _start_claim_task(self, p, team, main, rnd):
        tid = main.get("taskId")
        t = next((x for x in self.tasks if x["taskId"] == tid), None)
        if not t or t.get("failed"):
            self._result(p, rnd, main, accepted=False, code="TASK_NOT_AVAILABLE")
            return
        if t.get("nodeId") != p.pos:
            self._result(p, rnd, main, accepted=False, code="NOT_AT_TARGET_NODE")
            return
        # 每玩家独立完成：本玩家已领过 → OBJECT_BUSY（复现实局重复领取拒绝语义）
        if p.player_id in t.get("completed_by", set()):
            self._result(p, rnd, main, accepted=False, code="OBJECT_BUSY")
            return
        frames = t.get("processRound", 3) or 3
        frames = self._maybe_scout_reduce(p, team, p.pos, frames, 2)
        p.current_process = {"node": p.pos, "type": "CLAIM_TASK", "remaining": frames, "ctx": tid}
        p.state = PlayerState.PROCESSING
        self._result(p, rnd, main, accepted=True)

    def _use_resource(self, p, team, main, rnd):
        res = main.get("resourceType")
        if res == "ICE_BOX":
            if p.resource_count("ICE_BOX") <= 0 or p.freshness <= 0:
                self._result(p, rnd, main, accepted=False, code="RESOURCE_NOT_AVAILABLE")
                return
            p.freshness = min(100.0, p.freshness + 10)
            p.resources["ICE_BOX"] -= 1
            self.events.append({"type": "RESOURCE_USE", "round": rnd, "payload": {"playerId": p.player_id, "resourceType": "ICE_BOX"}})
            self._result(p, rnd, main, accepted=True)
            return
        if res in ("FAST_HORSE", "SHORT_HORSE"):
            if p.resource_count(res) <= 0:
                self._result(p, rnd, main, accepted=False, code="RESOURCE_NOT_AVAILABLE")
                return
            if p.active_move_buff() is not None:  # 马类/疾行互斥
                self._result(p, rnd, main, accepted=False, code="HORSE_BUFF_CONFLICT")
                return
            p.buffs.append({"type": res, "remaining": rules.HORSE_DURATION[res]})
            p.resources[res] -= 1
            self.events.append({"type": "RESOURCE_USE", "round": rnd, "payload": {"playerId": p.player_id, "resourceType": res}})
            self._result(p, rnd, main, accepted=True)
            return
        if res == "INTEL":
            if p.resource_count("INTEL") <= 0:
                self._result(p, rnd, main, accepted=False, code="RESOURCE_NOT_AVAILABLE")
                return
            tgt = main.get("targetNodeId")
            if not tgt or self.game_map.route_distance(p.pos, tgt) > 15:
                self._result(p, rnd, main, accepted=False, code="TARGET_NOT_REACHABLE")
                return
            p.resources["INTEL"] -= 1
            self._add_scout_mark(tgt, team, rnd)
            self.events.append({"type": "RESOURCE_USE", "round": rnd, "payload": {"playerId": p.player_id, "resourceType": "INTEL", "targetNodeId": tgt}})
            self.events.append({"type": "SCOUT_MARKER_ADD", "round": rnd, "payload": {"nodeId": tgt, "teamId": team}})
            self._result(p, rnd, main, accepted=True)
            return
        self._result(p, rnd, main, accepted=False, code="RESOURCE_NOT_AVAILABLE")

    # ---- 急策 ----

    def _rush_protect(self, p, team, main, rnd):
        if self.phase != Phase.RUSH or p.rush_tactic_used > 0:
            self._result(p, rnd, main, accepted=False, code="RUSH_TACTIC_INVALID_BINDING")
            return
        # 仅停靠可提交（client 已保证；sim 兜底）
        p.buffs.append({"type": "RUSH_PROTECT", "remaining": rules.RUSH_PROTECT_DURATION})
        p.rush_tactic_used += 1
        self.events.append({"type": "RUSH_TACTIC_USE", "round": rnd, "payload": {"playerId": p.player_id, "tactic": "RUSH_PROTECT"}})
        self._result(p, rnd, main, accepted=True)

    def _rush_speed(self, p, team, main, rnd):
        if self.phase != Phase.RUSH or p.rush_tactic_used > 0:
            self._result(p, rnd, main, accepted=False, code="RUSH_TACTIC_INVALID_BINDING")
            return
        if p.active_move_buff() is not None:  # 与马类互斥
            self._result(p, rnd, main, accepted=False, code="HORSE_BUFF_CONFLICT")
            return
        p.buffs.append({"type": "RUSH_SPEED", "remaining": rules.RUSH_SPEED_DURATION})
        p.rush_tactic_used += 1
        self.events.append({"type": "RUSH_TACTIC_USE", "round": rnd, "payload": {"playerId": p.player_id, "tactic": "RUSH_SPEED"}})
        self._result(p, rnd, main, accepted=True)

    # ---- 设卡 / 攻坚 / 强制通行 ----

    def _start_set_guard(self, p, team, main, rnd):
        node = main.get("targetNodeId") or p.pos
        if node != p.pos:
            self._result(p, rnd, main, accepted=False, code="NOT_AT_TARGET_NODE")
            return
        if p.guard_action_point <= 0:
            self._result(p, rnd, main, accepted=False, code="OBJECT_BUSY")
            return
        extra = int(main.get("extraGoodFruit") or 0)
        if extra > 0 and p.good_fruit < extra:
            self._result(p, rnd, main, accepted=False, code="PARAM_OUT_OF_RANGE")
            return
        p.guard_action_point -= 1
        if extra > 0:
            p.good_fruit -= extra
        p.current_process = {"node": node, "type": "SET_GUARD", "remaining": GUARD_SETUP_FRAMES, "ctx": {"extra": extra}}
        p.state = PlayerState.PROCESSING
        self._result(p, rnd, main, accepted=True)

    def _break_guard(self, p, team, main, rnd):
        tgt = main.get("targetNodeId")
        g = self.guards.get(tgt)
        if not g or not g["active"] or g["defense"] <= 0:
            self._result(p, rnd, main, accepted=False, code="OBSTACLE_NOT_FOUND")
            return
        break_order = main.get("rushTactic") == "BREAK_ORDER"
        if break_order and (self.phase != Phase.RUSH or p.rush_tactic_used > 0):
            self._result(p, rnd, main, accepted=False, code="RUSH_TACTIC_INVALID_BINDING")
            return
        good = int(main.get("goodFruit") or 0)
        bad = int(main.get("badFruit") or 0)
        if good > p.good_fruit or bad > p.bad_fruit:
            self._result(p, rnd, main, accepted=False, code="PARAM_OUT_OF_RANGE")
            return
        attack = rules.break_guard_attack_value(good, bad, break_order)
        if break_order:
            p.rush_tactic_used += 1
        if attack >= g["defense"]:
            # 破卡成功
            self.guards.pop(tgt, None)
            p.good_fruit -= good
            p.bad_fruit -= bad
            self.events.append({"type": "GUARD_BREAK", "round": rnd, "payload": {"playerId": p.player_id, "nodeId": tgt}})
            self._result(p, rnd, main, accepted=True)
        elif attack > 0:
            # 攻坚失败：防守 -attack，攻方休整 5 帧
            g["defense"] = max(0, g["defense"] - attack)
            p.good_fruit -= good
            p.bad_fruit -= bad
            p.rest_remaining = REST_AFTER_BREAK_FAIL
            p.state = PlayerState.RESTING
            self.events.append({"type": "GUARD_BREAK_FAIL", "round": rnd, "payload": {"playerId": p.player_id, "nodeId": tgt}})
            self._result(p, rnd, main, accepted=True)
        else:
            self._result(p, rnd, main, accepted=False, code="PARAM_OUT_OF_RANGE")

    def _forced_pass(self, p, team, main, rnd):
        tgt = main.get("targetNodeId")
        if tgt is None:
            self._result(p, rnd, main, accepted=False, code="PARAM_OUT_OF_RANGE")
            return
        if tgt != p.pos and tgt not in self.game_map.neighbors(p.pos):
            self._result(p, rnd, main, accepted=False, code="NOT_AT_TARGET_NODE")
            return
        g = self.guards.get(tgt)
        defense = g["defense"] if g and g["active"] else 0
        has_obs = tgt in self.obstacles
        if not has_obs and defense <= 0:
            self._result(p, rnd, main, accepted=False, code="OBSTACLE_NOT_FOUND")
            return
        ntype = self.node_types.get(tgt)
        kind = _guard_kind(ntype, tgt == self.gate, has_obs)
        tax = rules.OBSTACLE_TIME_TAX if (has_obs and defense <= 0) else rules.guard_time_tax(kind, defense)
        p.current_process = {"node": tgt, "type": "FORCED_PASS", "remaining": tax, "ctx": None}
        p.state = PlayerState.FORCED_PASSING
        self.events.append({"type": "FORCED_PASS", "round": rnd,
                            "payload": {"playerId": p.player_id, "nodeId": tgt, "tax": tax}})
        self._result(p, rnd, main, accepted=True)

    # ---- 交付 ----

    def _deliver(self, p, team, main, rnd):
        if p.pos != self.terminal:
            self._result(p, rnd, main, accepted=False, code="DELIVER_NOT_AT_TERMINAL")
            return
        if not p.verified:
            self._result(p, rnd, main, accepted=False, code="VERIFY_REQUIRED")
            return
        if p.good_fruit <= 0 or p.freshness <= 0:
            self._result(p, rnd, main, accepted=False, code="DELIVER_NO_GOOD_FRUIT")
            return
        p.delivered = True
        p.deliver_round = rnd
        p.state = PlayerState.DELIVERED
        self.events.append({"type": "DELIVER_SUCCESS", "round": rnd, "payload": {"playerId": p.player_id}})
        self._result(p, rnd, main, accepted=True)

    # ---- 小分队 ----

    def _apply_squad(self, p, team, squad, rnd):
        a = squad.get("action")
        tgt = squad.get("targetNodeId")
        if a == "SQUAD_SCOUT" and p.squad_available >= SQUAD_SCOUT_COST and tgt:
            p.squad_available -= SQUAD_SCOUT_COST
            self.pending_squad.append({"arrive": rnd + SQUAD_DELAY, "node": tgt, "team": team, "kind": "SQUAD_SCOUT"})
            self._result_squad(p, rnd, squad, True)
        elif a == "SQUAD_CLEAR" and p.squad_available >= SQUAD_CLEAR_COST and tgt in self.obstacles:
            p.squad_available -= SQUAD_CLEAR_COST
            self.pending_squad.append({"arrive": rnd + SQUAD_DELAY, "node": tgt, "team": team, "kind": "SQUAD_CLEAR"})
            self._result_squad(p, rnd, squad, True)
        elif a in ("SQUAD_WEAKEN", "SQUAD_REINFORCE") and p.squad_available >= SQUAD_OTHER_COST and tgt:
            p.squad_available -= SQUAD_OTHER_COST
            self.pending_squad.append({"arrive": rnd + SQUAD_DELAY, "node": tgt, "team": team, "kind": a})
            self._result_squad(p, rnd, squad, True)
        else:
            self._result_squad(p, rnd, squad, False, code="PARAM_OUT_OF_RANGE")

    # ---- 鲜度 / 好→坏 / 风化 / buff ----

    def _settle_freshness(self, p, rnd):
        if p.delivered or p.retired:
            return
        if p.route_edge is not None and p.state == PlayerState.MOVING:
            base = rules.FRESHNESS_LOSS_MOVE.get(p.route_edge.route_type, rules.FRESHNESS_LOSS_BASE)
        else:
            base = rules.FRESHNESS_LOSS_BASE
        wtype = self._active_weather(rnd)
        rt = p.route_edge.route_type if p.route_edge is not None else None
        wcoef = self._weather_fresh_coef(rt, wtype)
        rcoef = 1.0
        if p.has_buff("RUSH_PROTECT"):
            rcoef = rules.FRESHNESS_RUSH_COEF["RUSH_PROTECT"]
        elif p.has_buff("RUSH_SPEED"):
            rcoef = rules.FRESHNESS_RUSH_COEF["RUSH_SPEED"]
        before = p.freshness
        p.freshness = max(0.0, p.freshness - rules.freshness_loss(base, wcoef, rcoef))
        for _t in rules.crossed_good_to_bad_thresholds(before, p.freshness):
            if p.good_fruit > 0:
                p.good_fruit -= 1
                p.bad_fruit += 1
            self.events.append({"type": "GOOD_TO_BAD", "round": rnd, "payload": {"playerId": p.player_id}})

    def _weather_guards(self):
        for g in self.guards.values():
            if g["active"] and g["defense"] > 0:
                g["defense"] = max(0, g["defense"] - 1)

    def _tick_buffs(self, p):
        for b in p.buffs:
            b["remaining"] -= 1
        p.buffs = [b for b in p.buffs if b["remaining"] > 0]

    # ---- actionResult ----

    def _result(self, p, rnd, action, accepted, code=None):
        self.action_results.append({
            "round": rnd, "playerId": p.player_id,
            "action": (action or {}).get("action"),
            "accepted": accepted,
            "errorCode": code if not accepted else None,
            "result": "ACCEPTED" if accepted else "REJECTED",
        })
        if not accepted:
            p.illegal_action_count += 1
            self.events.append({"type": "ACTION_REJECTED", "round": rnd,
                                "payload": {"playerId": p.player_id, "errorCode": code,
                                            "action": (action or {}).get("action"),
                                            "targetNodeId": (action or {}).get("targetNodeId")}})

    def _result_squad(self, p, rnd, squad, accepted, code=None):
        self.action_results.append({
            "round": rnd, "playerId": p.player_id,
            "action": squad.get("action"),
            "accepted": accepted, "errorCode": code if not accepted else None,
            "result": "ACCEPTED" if accepted else "REJECTED",
        })
        if not accepted:
            p.illegal_action_count += 1

    # ---- inquire 构造 ----

    def build_inquire(self, team):
        """构造该队视角的 inquire_data（me 在前，opp 在后）。"""
        p = self.players[team]
        opp = self.players[Team.BLUE if team == Team.RED else Team.RED]
        rnd = self.round
        return {
            "matchId": self.match_id,
            "round": rnd,
            "tick": max(0, rnd - 1),
            "phase": self.phase,
            "players": [self._player_view(p), self._player_view(opp)],
            "nodes": self._nodes_view(),
            "tasks": self._tasks_view(p.player_id),
            "contests": [],
            "bounties": [],
            "weather": self._weather_view(rnd),
            "events": list(self.events),
            "actionResults": list(self.action_results),
            "scorePreview": {Team.RED: self.players[Team.RED].task_score,
                             Team.BLUE: self.players[Team.BLUE].task_score},
        }

    def _player_view(self, p):
        route_edge_id = None
        if p.route_edge is not None:
            route_edge_id = p.route_edge.edge_id
        need = 0.0
        if p.route_edge is not None:
            need = rules.to_station_move_amount(p.route_edge.distance, p.route_edge.route_type)
        progress = (p.move_accum / need) if need else 0.0
        return {
            "playerId": p.player_id, "teamId": p.team_id, "camp": p.camp,
            "state": p.state, "currentNodeId": p.pos, "nextNodeId": p.next_node,
            "routeEdgeId": route_edge_id, "moveProgress": round(progress, 4),
            "freshness": round(p.freshness, 3), "goodFruit": p.good_fruit,
            "frozenGoodFruit": p.frozen_good_fruit, "badFruit": p.bad_fruit,
            "squadAvailable": p.squad_available, "guardActionPoint": p.guard_action_point,
            "verified": p.verified, "delivered": p.delivered, "retired": p.retired,
            "missingActionRounds": p.missing_action_rounds, "illegalActionCount": p.illegal_action_count,
            "penaltyScore": p.penalty_score, "rushTacticUsedCount": p.rush_tactic_used,
            "resources": {k: v for k, v in p.resources.items() if v > 0},
            "buffs": [{"type": b["type"], "remainingRound": b["remaining"]} for b in p.buffs],
            "currentProcess": self._process_view(p),
            "taskScore": p.task_score, "bountyScore": p.bounty_score,
            "totalScore": self._live_score(p),
        }

    def _process_view(self, p):
        cp = p.current_process
        if cp is None:
            return None
        return {"nodeId": cp["node"], "processType": cp["type"], "remainingRound": cp["remaining"]}

    def _nodes_view(self):
        out = []
        for nid, ntype in self.node_types.items():
            scouted = [{"teamId": m["team"], "remainRound": max(0, m["expire"] - self.round),
                        "processReduceRound": PROCESS_SCOUT_REDUCE, "remainingTriggers": 1}
                       for m in self.scout_marks.get(nid, [])]
            g = self.guards.get(nid)
            guard = None
            if g and g["active"]:
                guard = {"ownerTeamId": g["owner"], "defense": g["defense"], "active": True}
            out.append({
                "nodeId": nid, "nodeType": ntype,
                "resourceStock": dict(self.resource_stock.get(nid, {})),
                "hasObstacle": nid in self.obstacles,
                "obstacleType": self.obstacles.get(nid, {}).get("type") if nid in self.obstacles else None,
                "scouted": scouted, "guard": guard, "canWindow": False,
            })
        return out

    def _tasks_view(self, pid):
        """每玩家视角：本玩家已完成的任务标 completed=True（供 world.active_tasks 过滤）。

        跨玩家不互斥（双方各自独立完成），故不以全局 completed 屏蔽对端。
        """
        out = []
        for t in self.tasks:
            tt = {k: v for k, v in t.items() if k != "completed_by"}
            tt["completed"] = pid in t.get("completed_by", set())
            out.append(tt)
        return out

    def _weather_view(self, rnd):
        wtype = self._active_weather(rnd)
        active = [{"type": wtype, "roundsRemaining": max(0, self._weather_remaining(rnd, wtype))}] if wtype else []
        nxt = self._next_weather(rnd)
        nextv = [{"type": nxt["type"], "startIn": nxt["startIn"]}] if nxt else []
        return {"active": active, "next": nextv}

    def _weather_remaining(self, rnd, wtype):
        for w in self.weather_schedule:
            if w["type"] == wtype and w["start"] <= rnd <= w["end"]:
                return w["end"] - rnd + 1
        return 0

    # ---- 评分 ----

    def _live_score(self, p):
        """运行期粗估分（仅 totalScore 字段，供投影/显示；终局以 final_score 为准）。"""
        if p.delivered:
            return self._score_detail(p)["total"]
        return rules.task_score(p.task_score, delivered=False) + rules.bounty_score(p.bounty_score, delivered=False)

    def _score_detail(self, p):
        """用 rules.py 计算终局分项（交付/未交付口径）。"""
        if p.delivered:
            detail = {
                "delivery": rules.delivery_base_score(p.task_score),
                "task": rules.task_score(p.task_score, delivered=True),
                "time": rules.time_score(p.deliver_round, p.task_score),
                "goodFruit": rules.good_fruit_score(p.good_fruit),
                "freshness": rules.freshness_score(p.freshness),
                "bounty": rules.bounty_score(p.bounty_score, delivered=True),
                "penalty": p.penalty_score,
            }
        else:
            detail = {
                "delivery": 0, "time": 0, "goodFruit": 0, "freshness": 0,
                "task": rules.task_score(p.task_score, delivered=False),
                "bounty": rules.bounty_score(p.bounty_score, delivered=False),
                "penalty": p.penalty_score,
            }
        detail["total"] = rules.total_score(
            [detail["delivery"], detail["task"], detail["time"],
             detail["goodFruit"], detail["freshness"], detail["bounty"]],
            detail["penalty"])
        return detail

    def final_score(self, team):
        return self._score_detail(self.players[team])

    def build_over_data(self):
        """构造 over 消息载荷（供 trace Over/Score + 对账自检）。"""
        over_round = self.round
        wteam = self.winner_team()
        winner_pid = self.players[wteam].player_id if wteam is not None else None
        both_delivered = all(p.delivered for p in self.players.values())
        reason = ("ALL_DELIVERED" if both_delivered
                  else ("TIME_LIMIT" if over_round >= self.duration_round else "ENDED"))
        return {
            "matchId": self.match_id, "overRound": over_round,
            "resultType": "NORMAL", "overReason": reason,
            "winnerPlayerId": winner_pid,
            "players": [self._player_over(self.players[Team.RED]),
                        self._player_over(self.players[Team.BLUE])],
        }

    def _player_over(self, p):
        # scoreDetail 对齐协议键名（tasks 复数；sim _score_detail 用 task 单数），供 trace Score 行携带分项
        detail = self._score_detail(p)
        score_detail = dict(detail)
        if "task" in score_detail:
            score_detail["tasks"] = score_detail.pop("task")
        return {
            "playerId": p.player_id, "delivered": p.delivered, "retired": p.retired,
            "freshness": round(p.freshness, 3), "goodFruit": p.good_fruit,
            "taskScore": p.task_score, "bountyScore": p.bounty_score,
            "deliverRound": p.deliver_round if p.delivered else 0,
            "totalScore": detail["total"],
            "scoreDetail": score_detail,
        }

    def is_ended(self):
        return self.phase == Phase.ENDED

    def winner_team(self):
        rs = self.final_score(Team.RED)["total"]
        bs = self.final_score(Team.BLUE)["total"]
        if rs > bs:
            return Team.RED
        if bs > rs:
            return Team.BLUE
        return None
