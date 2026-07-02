"""决策引擎。

M3 基线（稳定交付）：最短路推进 → 固定处理 → 宫门 RUSH 验核 → 交付。
M4 收益（在 M3 之上，稳定交付仍是硬约束）：
  - 时间感知路由：按 GameMap.time_optimal_path（帧数含固定处理耗时）选下一跳。
  - 皇榜任务：机会式完成"目标即当前节点"的任务（不绕路），拉高任务基础分累计
    （达 90 解锁满额送达基础分/用时系数，并触发里程碑奖励）。
  - 资源领取：在有货节点领取所缺的高价值资源（冰鉴保鲜、马加速）。
  - 鲜度管理：鲜度偏低时用冰鉴护住阈值与鲜度分。
  - 加速：长途移动中若持马且无移动增益则用马（省时又省鲜度）。
  - 护果令：RUSH 阶段鲜度偏低时用护果令保住终局鲜度。
所有"额外读条"（任务/领取）都过时间预算守卫：确保仍能在 600 帧内交付。

策略与通信解耦：只依赖 core.WorldState / GameMap，不 import socket。
对抗（设卡/攻坚/强制通行/窗口/小分队）留待 M5。
"""

import config
from core.game_map import GameMap
from protocol import actions
from protocol.enums import PlayerState, ResourceType

_IDLE_LIKE = (PlayerState.IDLE, PlayerState.COST_BANKRUPT, None)
_MOVE_BUFF_TYPES = frozenset({ResourceType.FAST_HORSE, ResourceType.SHORT_HORSE, "RUSH_SPEED"})


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
            # 移动中：仅可用马类；长途无增益则加速
            if me.state in (PlayerState.MOVING, PlayerState.WAITING):
                horse = self._maybe_horse(me, gm, terminal)
                return [horse] if horse else []
            if me.state not in _IDLE_LIKE:
                return []
            return self._plan(world, me, gm, node, terminal, gate)
        finally:
            self._prev_state = me.state

    # ---- 主计划（空闲态，在节点）----

    def _plan(self, world, me, gm, node, terminal, gate):
        # 鲜度急救：在节点用冰鉴护住阈值
        rescue = self._freshness_rescue(me)
        if rescue:
            return [rescue]

        # 终点
        if terminal and node == terminal:
            if me.verified and me.good_fruit > 0 and me.freshness > 0:
                return [actions.deliver()]
            if not me.verified and gate:
                return self._move_toward(gm, node, gate)  # 异常：回宫门补验核
            return []

        # 宫门
        if gate and node == gate:
            if not me.verified:
                if world.is_rush:
                    rp = self._maybe_rush_protect(world, me)
                    if rp:
                        return [rp]
                    return [actions.verify_gate()]
                # 普通阶段候场：可机会式做任务/领取
                return self._opportunistic(world, me, gm, node, terminal) or []
            return self._move_toward(gm, node, terminal)

        # 固定处理站点：离站前必须先处理
        if node in gm.process_nodes and not self._processed_here:
            return [actions.process()]

        # RUSH 途中护果令保鲜
        rp = self._maybe_rush_protect(world, me)
        if rp:
            return [rp]

        # 机会式任务/资源领取
        opp = self._opportunistic(world, me, gm, node, terminal)
        if opp:
            return opp

        # 时间感知路由推进
        if terminal:
            return self._move_toward(gm, node, terminal)
        return []

    def _opportunistic(self, world, me, gm, node, terminal):
        task = self._maybe_task(world, me, gm, node, terminal)
        if task:
            return [task]
        claim = self._maybe_claim(world, me, gm, node, terminal)
        if claim:
            return [claim]
        return None

    def _move_toward(self, gm, src, dst):
        path, _ = gm.time_optimal_path(src, dst)
        if path and len(path) > 1:
            return [actions.move(path[1])]
        return []

    # ---- 收益子策略 ----

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
                continue  # 对方保护期内，别抢
            owner = t.get("ownerPlayerId") or 0
            if owner and owner != pid:
                continue  # 已被对方占用
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
        if not horse:
            return None
        if not self._far_from_terminal(gm, me.current_node_id, terminal):
            return None
        return actions.use_resource(horse)

    def _maybe_rush_protect(self, world, me):
        if not world.is_rush or me.delivered:
            return None
        if (me.rush_tactic_used_count or 0) > 0:
            return None
        if me.freshness >= config.RUSH_PROTECT_FRESHNESS_BELOW:
            return None
        return actions.rush_protect()

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
        """做完 extra_frames 读条后，估算仍能在总帧数内交付。"""
        if terminal is None:
            return True
        _, travel = gm.time_optimal_path(node, terminal)
        if travel == float("inf"):
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
