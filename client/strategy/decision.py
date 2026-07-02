"""决策引擎。

M3 基线策略（稳定交付优先）：
    最短路推进 → 到达固定处理站点先 PROCESS → 到宫门 S14 在 RUSH 阶段 VERIFY_GATE
    → 验核后进入终点 S15 → 满足条件 DELIVER。
非空闲态（MOVING/PROCESSING/VERIFYING/RESTING/CONTESTING/FORCED_PASSING）发空动作心跳，
让服务端按当前状态推进；已交付后只心跳，避免交付后违规扣分。

策略与通信解耦：只依赖 core.WorldState / GameMap，不 import socket。
资源/任务/对抗/终局急策留待 M4/M5。
"""

from core.game_map import GameMap
from protocol import actions
from protocol.enums import PlayerState

# 视为可决策的“空闲类”状态：可提交主车队动作
_IDLE_LIKE = (PlayerState.IDLE, PlayerState.COST_BANKRUPT, None)


class GameContext:
    """跨帧静态/半静态上下文（开局缓存）。承载地图镜像 GameMap 与本方身份。"""

    def __init__(self, player_id, team_id=None, camp=None, start_data=None):
        self.player_id = int(player_id)
        self.team_id = team_id
        self.camp = camp
        start_data = start_data or {}
        self.match_id = start_data.get("matchId")
        self.duration_round = start_data.get("durationRound")
        self.task_templates = start_data.get("taskTemplates", [])
        try:
            self.game_map = GameMap(start_data)
        except Exception:
            self.game_map = None


class DecisionEngine:
    def __init__(self, context):
        self.ctx = context
        # 处理完成跟踪：记录当前停留节点，及该次停留的固定处理是否已完成
        self._stay_node = None
        self._processed_here = False
        self._prev_state = None

    def decide(self, world):
        """返回本帧 actions 列表（core.WorldState 输入）。"""
        me = world.me
        gm = self.ctx.game_map
        if me is None or gm is None:
            return []

        node = me.current_node_id
        self._update_process_memory(world, me, node)

        try:
            result = self._plan(world, me, gm, node)
        finally:
            self._prev_state = me.state
        return result

    # ---- 主计划 ----

    def _plan(self, world, me, gm, node):
        # 已交付：只心跳
        if me.delivered or me.state == PlayerState.DELIVERED:
            return []
        # 非空闲态：让服务端推进移动/读条/验核/休整
        if me.state not in _IDLE_LIKE:
            return []

        terminal = gm.terminal_nodes[0] if gm.terminal_nodes else None
        gate = gm.gate_node

        # 1) 已在终点
        if terminal and node == terminal:
            if me.verified and me.good_fruit > 0 and me.freshness > 0:
                return [actions.deliver()]
            if not me.verified and gate:
                return self._move_toward(gm, node, gate)  # 异常：回宫门补验核
            return []  # 已验核但暂不满足交付条件 → 等待

        # 2) 在宫门
        if gate and node == gate:
            if not me.verified:
                if world.is_rush:
                    return [actions.verify_gate()]
                return []  # 普通阶段：停在宫门等待宫宴冲刺
            if terminal:
                return self._move_toward(gm, node, terminal)
            return []

        # 3) 固定处理站点：离站前必须先处理
        if node in gm.process_nodes and not self._processed_here:
            return [actions.process()]

        # 4) 沿最短路推进（路径经过宫门，宫门逻辑会拦停验核）
        if terminal:
            return self._move_toward(gm, node, terminal)
        return []

    def _move_toward(self, gm, src, dst):
        path, _cost = gm.shortest_path(src, dst, metric="move")
        if path and len(path) > 1:
            return [actions.move(path[1])]
        return []

    # ---- 处理完成跟踪 ----

    def _update_process_memory(self, world, me, node):
        # 换节点即重置本次停留的处理标记
        if node != self._stay_node:
            self._stay_node = node
            self._processed_here = False
        # 完成信号：本帧 PROCESS_COMPLETE 事件，或 PROCESSING→IDLE 状态跃迁
        if self._saw_process_complete(world) or (
            self._prev_state == PlayerState.PROCESSING and me.state != PlayerState.PROCESSING
        ):
            self._processed_here = True

    def _saw_process_complete(self, world):
        pid = self.ctx.player_id
        for e in world.events:
            if e.get("type") == "PROCESS_COMPLETE":
                payload = e.get("payload") or {}
                if payload.get("playerId") == pid:
                    return True
        return False
