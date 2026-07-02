"""决策引擎。

分层（每层在前一层之上，"稳定交付"始终是硬约束）：
- M3 基线：最短路推进 → 固定处理 → 宫门 RUSH 验核 → 交付。
- M4 收益：时间感知路由；机会式皇榜任务/资源领取；冰鉴保鲜；马加速；护果令。
- M5 对抗：
  * 阻塞感知路由：把道路障碍/敌方有效设卡节点视为不可进入，优先绕行。
  * 突破（无法绕行时）：障碍→T04(得分+清障)/CLEAR(耗好果)/FORCED_PASS；敌卡→BREAK_GUARD(含破关令)/FORCED_PASS。
  * 窗口出牌：参与本方窗口时按可支付牌出牌，否则弃权。
  * 终局急策二选一：鲜度低用护果令，远且鲜度健康且无马用疾行令。
  * 小分队探路宫门：临近宫门时派小分队探路，减少验核读条 3 帧。
基线不主动 SET_GUARD（占用己方交付时间，收益不确定）——action 能力已具备，留待专门的进攻/干扰策略。

策略与通信解耦：只依赖 core.WorldState / GameMap，不 import socket。
"""

import config
from core.game_map import GameMap
from protocol import actions
from protocol.enums import Action, Card, PlayerState, ResourceType

_IDLE_LIKE = (PlayerState.IDLE, PlayerState.COST_BANKRUPT, None)
_MOVE_BUFF_TYPES = frozenset({ResourceType.FAST_HORSE, ResourceType.SHORT_HORSE, "RUSH_SPEED"})
_INF = float("inf")


class GameContext:
    """跨帧静态/半静态上下文（开局缓存）。承载地图镜像 GameMap 与本方身份。"""

    def __init__(self, player_id, team_id=None, camp=None, start_data=None):
        self.player_id = int(player_id)
        self.team_id = team_id
        self.camp = camp
        start_data = start_data or {}
        self.match_id = start_data.get("matchId")
        self.duration_round = start_data.get("durationRound") or 600
        self.task_templates = start_data.get("taskTemplates", [])
        try:
            self.game_map = GameMap(start_data)
        except Exception:
            self.game_map = None


class DecisionEngine:
    def __init__(self, context):
        self.ctx = context
        self._stay_node = None
        self._processed_here = False
        self._prev_state = None
        self._gate_scout_sent = False

    def decide(self, world):
        me = world.me
        gm = self.ctx.game_map
        if me is None or gm is None:
            return []

        node = me.current_node_id
        self._update_process_memory(world, me, node)
        terminal = gm.terminal_nodes[0] if gm.terminal_nodes else None
        gate = gm.gate_node

        try:
            if me.delivered or me.state == PlayerState.DELIVERED:
                return []
            # 窗口出牌（本方参与的窗口）优先响应
            card = self._window_card(world, me)
            if card:
                return [card]

            if me.state in (PlayerState.MOVING, PlayerState.WAITING):
                main = self._maybe_horse(me, gm, terminal)
                main = [main] if main else []
            elif me.state in _IDLE_LIKE:
                main = self._plan(world, me, gm, node, terminal, gate)
            else:
                main = []

            squad = self._maybe_squad(world, me, gm, node)
            return main + ([squad] if squad else [])
        finally:
            self._prev_state = me.state

    # ---- 主计划（空闲态，在节点）----

    def _plan(self, world, me, gm, node, terminal, gate):
        rescue = self._freshness_rescue(me)
        if rescue:
            return [rescue]

        if terminal and node == terminal:
            if me.verified and me.good_fruit > 0 and me.freshness > 0:
                return [actions.deliver()]
            if not me.verified and gate:
                return self._advance(world, me, gm, node, gate, terminal)
            return []

        if gate and node == gate:
            if not me.verified:
                if world.is_rush:
                    rp = self._maybe_rush_protect(world, me)
                    if rp:
                        return [rp]
                    return [actions.verify_gate()]
                return self._opportunistic(world, me, gm, node, terminal) or []
            return self._advance(world, me, gm, node, terminal, terminal)

        if node in gm.process_nodes and not self._processed_here:
            return [actions.process()]

        rp = self._maybe_rush_protect(world, me)
        if rp:
            return [rp]

        opp = self._opportunistic(world, me, gm, node, terminal)
        if opp:
            return opp

        if terminal:
            return self._advance(world, me, gm, node, terminal, terminal)
        return []

    def _opportunistic(self, world, me, gm, node, terminal):
        task = self._maybe_task(world, me, gm, node, terminal)
        if task:
            return [task]
        claim = self._maybe_claim(world, me, gm, node, terminal)
        if claim:
            return [claim]
        return None

    # ---- 阻塞感知推进 + 突破 ----

    def _advance(self, world, me, gm, src, dst, terminal):
        blocked = self._blocked_nodes(world, me)
        path, _ = gm.time_optimal_path(src, dst, blocked=blocked)
        if path and len(path) > 1:
            # 有畅通去路时才考虑用疾行令（被阻挡时用疾行令是浪费）
            speed = self._rush_speed_warranted(world, me, gm, src, terminal)
            if speed:
                return [speed]
            return [actions.move(path[1])]  # 正常/绕行
        # 无法绕行：沿忽略阻塞的最短路，突破下一个阻塞节点
        upath, _ = gm.time_optimal_path(src, dst)
        if not upath or len(upath) < 2:
            return []
        return self._breakthrough(world, me, gm, upath[1], terminal)

    def _blocked_nodes(self, world, me):
        blocked = set()
        for nid, ns in world.node_states.items():
            if ns.has_obstacle:
                blocked.add(nid)
            owner = ns.active_guard_owner()
            if owner and owner != me.team_id:
                blocked.add(nid)
        return blocked

    def _breakthrough(self, world, me, gm, nxt, terminal):
        ns = world.node(nxt)
        # 道路障碍
        if ns and ns.has_obstacle:
            t04 = self._find_t04(world, nxt)
            if t04 and self._can_afford(world, gm, me.current_node_id, t04.get("processRound", 6) or 6, terminal):
                return [actions.claim_task(t04.get("taskId"))]
            if me.good_fruit > config.KEEP_GOOD_FRUIT_MIN:
                return [actions.clear(nxt)]
            return [actions.forced_pass(nxt)]
        # 敌方有效设卡
        owner = ns.active_guard_owner() if ns else None
        if owner and owner != me.team_id:
            plan = self._plan_attack(world, me, ns)
            if plan is not None:
                g, b, bo = plan
                return [actions.break_guard(nxt, good_fruit=g, bad_fruit=b,
                                            rush_tactic=(Action.BREAK_ORDER if bo else None))]
            return [actions.forced_pass(nxt)]
        return [actions.move(nxt)]  # 兜底

    def _find_t04(self, world, node):
        for t in world.active_tasks():
            if t.get("taskTemplateId") == "T04" and t.get("nodeId") == node:
                return t
        return None

    def _plan_attack(self, world, me, ns):
        """规划攻坚投入：好/坏果各 ≤2，攻坚值 ≥ 防守值，且保留最低好果。返回 (good,bad,break_order) 或 None。"""
        defense = (ns.guard or {}).get("defense", 0) or 0
        if defense <= 0:
            return None
        bo = world.is_rush and (me.rush_tactic_used_count or 0) == 0
        bonus = 3 if bo else 0
        best = None
        for g in range(0, 3):
            if g > me.good_fruit or (me.good_fruit - g) < config.KEEP_GOOD_FRUIT_MIN:
                continue
            for b in range(0, 3):
                if b > me.bad_fruit:
                    continue
                if g * 2 + b * 3 + bonus >= defense:
                    if best is None or (g, b) < (best[0], best[1]):
                        best = (g, b, bo)
        return best

    # ---- 收益子策略（M4）----

    def _freshness_rescue(self, me):
        if me.resource_count(ResourceType.ICE_BOX) > 0 and 0 < me.freshness < config.ICE_BOX_USE_BELOW:
            return actions.use_resource(ResourceType.ICE_BOX)
        return None

    def _maybe_task(self, world, me, gm, node, terminal):
        pid = self.ctx.player_id
        for t in world.active_tasks():
            if t.get("nodeId") != node:
                continue
            if t.get("taskTemplateId") in config.SKIP_TASK_TEMPLATES:
                continue
            prot = t.get("protectionPlayerId") or 0
            if prot and prot != pid:
                continue
            owner = t.get("ownerPlayerId") or 0
            if owner and owner != pid:
                continue
            pr = t.get("processRound", 0) or 0
            if not self._can_afford(world, gm, node, pr, terminal):
                continue
            return actions.claim_task(t.get("taskId"))
        return None

    def _maybe_claim(self, world, me, gm, node, terminal):
        ns = world.node(node)
        if ns is None:
            return None
        wants = []
        if me.resource_count(ResourceType.ICE_BOX) < config.CLAIM_ICE_BOX_KEEP \
                and ns.resource_available(ResourceType.ICE_BOX):
            wants.append(ResourceType.ICE_BOX)
        if not self._has_any_horse(me) and self._far_from_terminal(gm, node, terminal):
            if ns.resource_available(ResourceType.FAST_HORSE):
                wants.append(ResourceType.FAST_HORSE)
            elif ns.resource_available(ResourceType.SHORT_HORSE):
                wants.append(ResourceType.SHORT_HORSE)
        for r in wants:
            if self._can_afford(world, gm, node, config.RESOURCE_CLAIM_ROUND, terminal):
                return actions.claim_resource(node, r)
        return None

    def _maybe_horse(self, me, gm, terminal):
        if self._has_move_buff(me):
            return None
        horse = None
        if me.resource_count(ResourceType.FAST_HORSE) > 0:
            horse = ResourceType.FAST_HORSE
        elif me.resource_count(ResourceType.SHORT_HORSE) > 0:
            horse = ResourceType.SHORT_HORSE
        if not horse or not self._far_from_terminal(gm, me.current_node_id, terminal):
            return None
        return actions.use_resource(horse)

    def _maybe_rush_protect(self, world, me):
        """低鲜度时用护果令保鲜（可在被阻挡/等待时使用，不浪费）。"""
        if not world.is_rush or me.delivered or (me.rush_tactic_used_count or 0) > 0:
            return None
        if me.freshness < config.RUSH_PROTECT_FRESHNESS_BELOW:
            return actions.rush_protect()
        return None

    def _rush_speed_warranted(self, world, me, gm, node, terminal):
        """疾行令：仅在有畅通去路、远、鲜度健康、且无任何马类时（优先用马，马更省）。"""
        if not world.is_rush or me.delivered or (me.rush_tactic_used_count or 0) > 0:
            return None
        if me.freshness < config.RUSH_PROTECT_FRESHNESS_BELOW:
            return None  # 低鲜度优先护果令
        if self._has_any_horse(me) or not self._far_from_terminal(gm, node, terminal):
            return None
        return actions.rush_speed()

    def _maybe_squad(self, world, me, gm, node):
        """小分队探路宫门以减少验核读条。仅普通阶段（RUSH 禁止新派），临近宫门且尚无己方标记时一次。"""
        if world.is_rush or self._gate_scout_sent or (me.squad_available or 0) < 1:
            return None
        gate = gm.gate_node
        if not gate or not node:
            return None
        ns = world.node(gate)
        if ns and ns.my_scout_marks(me.team_id):
            self._gate_scout_sent = True
            return None
        _, frames = gm.time_optimal_path(node, gate)
        if frames == _INF or frames < config.GATE_SCOUT_MIN_FRAMES or frames > config.GATE_SCOUT_MAX_FRAMES:
            return None
        self._gate_scout_sent = True
        return actions.squad_scout(gate)

    # ---- 窗口出牌 ----

    def _window_card(self, world, me):
        contests = world.my_contests()
        if not contests:
            return None
        cid = contests[0].get("contestId")
        if not cid:
            return None
        if (me.guard_action_point or 0) > 0:
            return actions.window_card(cid, Card.BING_ZHENG)
        if me.freshness >= 80 and me.good_fruit > config.KEEP_GOOD_FRUIT_MIN:
            return actions.window_card(cid, Card.XIAN_GONG)
        if me.resource_count(ResourceType.PASS_TOKEN) > 0 or me.resource_count(ResourceType.OFFICIAL_PERMIT) > 0:
            return actions.window_card(cid, Card.YAN_DIE)
        if self._has_any_horse(me):
            return actions.window_card(cid, Card.QIANG_XING)
        return actions.window_card(cid, Card.ABSTAIN)

    # ---- 辅助 ----

    def _has_move_buff(self, me):
        for b in me.buffs:
            if b.get("type") in _MOVE_BUFF_TYPES and (b.get("remainingRound", 0) or 0) > 0:
                return True
        return False

    def _has_any_horse(self, me):
        return (me.resource_count(ResourceType.FAST_HORSE) > 0
                or me.resource_count(ResourceType.SHORT_HORSE) > 0
                or self._has_move_buff(me))

    def _far_from_terminal(self, gm, node, terminal):
        if not node or not terminal:
            return False
        return gm.route_distance(node, terminal) > config.HORSE_MIN_REMAINING_DISTANCE

    def _can_afford(self, world, gm, node, extra_frames, terminal):
        if terminal is None:
            return True
        _, travel = gm.time_optimal_path(node, terminal)
        if travel == _INF:
            return False
        end = (world.round or 0) + extra_frames + travel + config.DELIVER_TIME_SAFETY_MARGIN
        return end <= (self.ctx.duration_round or 600)

    # ---- 固定处理完成跟踪 ----

    def _update_process_memory(self, world, me, node):
        if node != self._stay_node:
            self._stay_node = node
            self._processed_here = False
        gm = self.ctx.game_map
        is_proc_node = gm is not None and node in gm.process_nodes
        transition_done = (is_proc_node and self._prev_state == PlayerState.PROCESSING
                           and me.state != PlayerState.PROCESSING)
        if self._saw_process_complete(world) or transition_done:
            self._processed_here = True

    def _saw_process_complete(self, world):
        pid = self.ctx.player_id
        for e in world.events:
            if e.get("type") == "PROCESS_COMPLETE":
                payload = e.get("payload") or {}
                if payload.get("playerId") == pid:
                    return True
        return False
