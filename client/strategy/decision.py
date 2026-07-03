"""决策引擎。

分层（每层在前一层之上，"稳定交付"始终是硬约束）：
- M3 基线：最短路推进 → 固定处理 → 宫门 RUSH 验核 → 交付。
- M4 收益：时间感知路由；机会式皇榜任务/资源领取；冰鉴保鲜；马加速；护果令。
- M5 对抗：阻塞感知路由(绕行)；突破(障碍 T04/CLEAR/强制通行；敌卡攻坚含破关令/强制通行)；窗口出牌；
  疾行令/护果令二选一；小分队探路宫门。
- M7 能力补全：
  * 拒绝反馈：读上一帧 actionResults/events，PROCESS_REQUIRED 强制处理、移动阻塞类临时拉黑目标（防循环）。
  * 情报(INTEL)：探路前方处理点/宫门（射程 15）减处理帧；并机会式领取情报。
  * 绕行 vs 清障权衡：绕行远超就地清障成本时改为清障。
  * 绕路做任务：任务分<90 且时间预算允许时，向近处任务节点绕行以拉高任务分。
  * 防御性小分队：预清路线前方障碍(SQUAD_CLEAR)/削弱前方敌卡(SQUAD_WEAKEN)。
  * 进攻干扰(默认关闭，config.ENABLE_OFFENSIVE)：关键关隘主动设卡。

策略与通信解耦：只依赖 core.WorldState / GameMap，不 import socket。
"""

import config
from core.game_map import GameMap
from protocol import actions
from protocol.enums import Action, Card, PlayerState, ResourceType
from strategy.projection import (Projector, RiskMode, net_score_delta,
                                  AVG_FRESHNESS_LOSS_PER_FRAME)
from strategy.tuning import tuning_for_mode

_IDLE_LIKE = (PlayerState.IDLE, PlayerState.COST_BANKRUPT, None)
_MOVE_BUFF_TYPES = frozenset({ResourceType.FAST_HORSE, ResourceType.SHORT_HORSE, "RUSH_SPEED"})
_MOVE_BLOCK_CODES = frozenset({"MOVE_BLOCKED_BY_GUARD", "TARGET_NOT_REACHABLE",
                               "MOVE_EDGE_NOT_FOUND", "OBJECT_BUSY"})
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
        self._cooldown = {}          # nodeId -> 拉黑截止回合（拒绝反馈）
        self._last_main_action = None
        self._squad_sent = set()     # (nodeId, kind) 已派出的小分队目标，避免重复
        # M8 博弈投影层（Layer 1，纯观测）：每帧构建只读投影总线，不改变任何动作。
        self.projector = Projector(context)
        self.projection_bus = None
        self.mode_change = None      # (from_mode, to_mode, reason, round) 仅切档当帧非空，供 trace
        # M8 Layer 2（P2 档位调参）：当前档位的策略参数；缺投影时回落 EVEN=既有默认。
        self.tuning = tuning_for_mode(RiskMode.EVEN)

    def decide(self, world):
        me = world.me
        gm = self.ctx.game_map
        if me is None or gm is None:
            return []

        node = me.current_node_id
        self._update_projection(world)
        self._apply_rejection_feedback(world)
        self._update_process_memory(world, me, node)
        terminal = gm.terminal_nodes[0] if gm.terminal_nodes else None
        gate = gm.gate_node

        result = []
        try:
            if me.delivered or me.state == PlayerState.DELIVERED:
                result = []
                return result
            card = self._window_card(world, me)
            if card:
                result = [card]
                return result
            # 移动中 / 主动等待中：主动续行，杜绝停滞（真实败局曾卡在 S14/WAITING 空等至 600 帧）
            if me.state in (PlayerState.MOVING, PlayerState.WAITING):
                result = self._keep_moving(world, me, gm, node, terminal, gate)
                return result
            if me.state not in _IDLE_LIKE:
                result = []
                return result
            main = self._plan(world, me, gm, node, terminal, gate)
            squad = self._maybe_squad(world, me, gm, node, terminal)
            result = main + ([squad] if squad else [])
            return result
        finally:
            self._prev_state = me.state
            self._last_main_action = self._extract_main(result)

    # ---- M8 投影总线（Layer 1，纯观测）----

    def _update_projection(self, world):
        """每帧构建只读投影总线、按档位刷新策略参数并记录切档事件。异常安全。"""
        try:
            self.projection_bus, changed, from_mode = self.projector.build(world)
            self.tuning = tuning_for_mode(self.projection_bus.mode)
            if changed:
                self.mode_change = (from_mode, self.projection_bus.mode,
                                    self.projection_bus.reason, world.round)
            else:
                self.mode_change = None
        except Exception:
            self.projection_bus = None
            self.mode_change = None
            self.tuning = tuning_for_mode(RiskMode.EVEN)

    # ---- 主计划（空闲态，在节点）----

    def _keep_moving(self, world, me, gm, node, terminal, gate):
        """处于移动中/主动等待中时保证持续前进，绝不空等卡死。

        - 值得加速且无移动增益 → 用一次马（不影响本帧继续前进）。
        - 有在途目标 → 重发 MOVE 到当前目标节点续行（协议允许，不改道、不清进度）。
        - 无在途目标（已在节点却被报为等待）→ 按节点空闲重新规划。
        """
        horse = self._maybe_horse(me, gm, terminal)
        if horse:
            return [horse]
        if me.next_node_id:
            return [actions.move(me.next_node_id)]
        return self._plan(world, me, gm, node, terminal, gate)

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

        intel = self._maybe_intel(world, me, gm, node, terminal)
        if intel:
            return [intel]

        rp = self._maybe_rush_protect(world, me)
        if rp:
            return [rp]

        opp = self._opportunistic(world, me, gm, node, terminal)
        if opp:
            return opp

        bounty = self._maybe_bounty(world, me, gm, node, terminal)
        if bounty:
            return bounty

        guard = self._maybe_set_guard(world, me, gm, node)
        if guard:
            return [guard]

        # 绕路做任务：任务分<90 且预算允许时，先去近处任务节点
        dst = self._task_detour_target(world, me, gm, node, terminal) or terminal
        if dst:
            return self._advance(world, me, gm, node, dst, terminal)
        return []

    def _opportunistic(self, world, me, gm, node, terminal):
        task = self._maybe_task(world, me, gm, node, terminal)
        if task:
            return [task]
        claim = self._maybe_claim(world, me, gm, node, terminal)
        if claim:
            return [claim]
        return None

    # ---- 阻塞感知推进 + 突破 + 绕行/清障权衡 ----

    def _advance(self, world, me, gm, src, dst, terminal):
        blocked = self._blocked_nodes(world, me)
        path_b, cost_b = gm.time_optimal_path(src, dst, blocked=blocked)
        path_u, cost_u = gm.time_optimal_path(src, dst)

        if path_b and len(path_b) > 1:
            # 绕行 vs 清障权衡：绕行远比就地清障贵，且直路下一跳是可清障障碍 → 就地清障
            if (path_u and len(path_u) > 1 and cost_b - cost_u > config.REROUTE_VS_CLEAR_EXTRA):
                nxt_u = path_u[1]
                ns = world.node(nxt_u)
                if (ns and ns.has_obstacle and me.good_fruit > config.KEEP_GOOD_FRUIT_MIN
                        and not self._is_cooldown(world, nxt_u)):
                    return self._breakthrough(world, me, gm, nxt_u, terminal)
            speed = self._rush_speed_warranted(world, me, gm, src, terminal)
            if speed:
                return [speed]
            return [actions.move(path_b[1])]

        # 无法绕行：沿忽略阻塞的最短路，突破下一个阻塞节点
        if not path_u or len(path_u) < 2:
            return []
        return self._breakthrough(world, me, gm, path_u[1], terminal)

    def _verify_frames(self, gm):
        info = gm.process_nodes.get(gm.gate_node) if gm.gate_node else None
        return (info.get("processRound") if info else 6) or 6

    def _deliver_estimate(self, world, me, gm, node, terminal):
        """从当前节点完成交付的估计帧数：路线到终点 + 未验核则加验核帧 + 少量缓冲（供 _can_afford）。"""
        if not terminal:
            return _INF
        _, travel = gm.time_optimal_path(node, terminal)
        if travel == _INF:
            return _INF
        est = travel + 2
        if not me.verified:
            est += self._verify_frames(gm)
        return est

    def _blocked_nodes(self, world, me):
        blocked = set()
        for nid, ns in world.node_states.items():
            if ns.has_obstacle:
                blocked.add(nid)
            owner = ns.active_guard_owner()
            if owner and owner != me.team_id:
                blocked.add(nid)
        rnd = world.round or 0
        for nid, exp in self._cooldown.items():
            if exp > rnd:
                blocked.add(nid)
        return blocked

    def _is_cooldown(self, world, nid):
        return self._cooldown.get(nid, 0) > (world.round or 0)

    def _breakthrough(self, world, me, gm, nxt, terminal):
        ns = world.node(nxt)
        if ns and ns.has_obstacle:
            t04 = self._find_t04(world, nxt)
            if t04 and self._can_afford(world, gm, me.current_node_id, t04.get("processRound", 6) or 6, terminal):
                return [actions.claim_task(t04.get("taskId"))]
            if me.good_fruit > config.KEEP_GOOD_FRUIT_MIN:
                return [actions.clear(nxt)]
            return [actions.forced_pass(nxt)]
        owner = ns.active_guard_owner() if ns else None
        if owner and owner != me.team_id:
            plan = self._plan_attack(world, me, ns)
            if plan is not None:
                g, b, bo = plan
                return [actions.break_guard(nxt, good_fruit=g, bad_fruit=b,
                                            rush_tactic=(Action.BREAK_ORDER if bo else None))]
            return [actions.forced_pass(nxt)]
        return [actions.move(nxt)]

    def _find_t04(self, world, node):
        for t in world.active_tasks():
            if t.get("taskTemplateId") == "T04" and t.get("nodeId") == node:
                return t
        return None

    def _plan_attack(self, world, me, ns):
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

    # ---- 拒绝反馈（M7）----

    def _apply_rejection_feedback(self, world):
        la = self._last_main_action
        if la is None:
            return
        code = self._my_reject_code(world)
        if not code:
            return
        if code == "PROCESS_REQUIRED":
            self._processed_here = False  # 强制在当前节点先完成固定处理
            return
        if la.get("action") == Action.MOVE and code in _MOVE_BLOCK_CODES:
            tgt = la.get("targetNodeId")
            if tgt:
                self._cooldown[tgt] = (world.round or 0) + config.REJECT_BLOCK_ROUNDS

    def _my_reject_code(self, world):
        pid = self.ctx.player_id
        prev = (world.round or 0) - 1
        for r in world.action_results:
            if r.get("playerId") == pid and r.get("round") == prev and r.get("accepted") is False:
                return r.get("errorCode")
        for e in world.events:
            if e.get("type") in ("ACTION_REJECTED", "INVALID_ACTION"):
                p = e.get("payload") or {}
                if p.get("playerId") == pid:
                    return p.get("errorCode")
        return None

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
        if me.resource_count(ResourceType.INTEL) < 1 and ns.resource_available(ResourceType.INTEL) \
                and self._intel_usable_ahead(world, me, gm, node, terminal):
            wants.append(ResourceType.INTEL)
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
        if not world.is_rush or me.delivered or (me.rush_tactic_used_count or 0) > 0:
            return None
        if me.freshness < self.tuning.rush_protect_freshness_below:  # §5.1 行4：按档位
            return actions.rush_protect()
        return None

    def _rush_speed_warranted(self, world, me, gm, node, terminal):
        if not world.is_rush or me.delivered or (me.rush_tactic_used_count or 0) > 0:
            return None
        if me.freshness < self.tuning.rush_protect_freshness_below:  # 鲜度危急优先护果，不冲刺
            return None
        if self._has_any_horse(me):  # 已有马加速，不叠加疾行
            return None
        racing, behind = self._endgame_race_state(world, me)
        if racing:
            # §5.3 终局 race：落后/接近抢交付帧（放宽"远离终点"门槛，只要仍有移动余量即冲）；
            # 领先则不烧疾行(+25%鲜度损耗)，把急策留给护果锁质量。
            return actions.rush_speed() if behind else None
        if not self._far_from_terminal(gm, node, terminal):  # 非 race：维持原保守门槛
            return None
        return actions.rush_speed()

    def _endgame_race_state(self, world, me):
        """§5.3 终局交付 race 判定：返回 (racing, behind)。

        racing = RUSH 相位下，对手投影将在 `ENDGAME_RACE_WINDOW` 帧内交付且我方也接近交付。
        behind = 投影分差 gap≤0（落后或接近）。缺投影/未到终局/信息不足 → (False, False)。
        终局 RUSH 相位对手路线已收敛，投影 confidence 天然偏高，可信度足以据此决策。
        """
        bus = self.projection_bus
        if not world.is_rush or bus is None or bus.opponent_projection is None:
            return (False, False)
        my, opp = bus.my_projection, bus.opponent_projection
        if my is None or my.deliver_frame is None or opp.deliver_frame is None:
            return (False, False)
        rnd = world.round or 0
        win = config.ENDGAME_RACE_WINDOW
        racing = (opp.deliver_frame - rnd) <= win and (my.deliver_frame - rnd) <= win
        return (racing, bus.gap <= 0)

    # ---- 情报 INTEL（M7）----

    def _reduce_targets_on_route(self, world, me, gm, node, terminal):
        """本方去路上的固定处理点/宫门（可被探路减时且尚无己方标记），按路径顺序。"""
        if not terminal:
            return []
        path, _ = gm.time_optimal_path(node, terminal, blocked=self._blocked_nodes(world, me))
        if not path or len(path) < 2:
            path, _ = gm.time_optimal_path(node, terminal)
        out = []
        for nxt in (path[1:] if path else []):
            if nxt == gm.gate_node or nxt in gm.process_nodes:
                ns = world.node(nxt)
                if ns and ns.my_scout_marks(me.team_id):
                    continue
                out.append(nxt)
        return out

    def _intel_usable_ahead(self, world, me, gm, node, terminal):
        """去路上是否存在"可在其前一节点用情报"的处理点/宫门（前驱到它的路线距离≤射程）。

        用于领取情报的守卫：避免在长边地图（每边>射程）上领取无法使用的情报。
        """
        if not terminal:
            return False
        path, _ = gm.time_optimal_path(node, terminal, blocked=self._blocked_nodes(world, me))
        if not path or len(path) < 2:
            path, _ = gm.time_optimal_path(node, terminal)
        if not path:
            return False
        for i in range(1, len(path)):
            p = path[i]
            if p == gm.gate_node or p in gm.process_nodes:
                ns = world.node(p)
                if ns and ns.my_scout_marks(me.team_id):
                    continue
                if gm.route_distance(path[i - 1], p) <= config.INTEL_RANGE:
                    return True
        return False

    def _maybe_intel(self, world, me, gm, node, terminal):
        if me.resource_count(ResourceType.INTEL) <= 0:
            return None
        for nxt in self._reduce_targets_on_route(world, me, gm, node, terminal):
            d = gm.route_distance(node, nxt)
            if d == _INF:
                continue
            if d > config.INTEL_RANGE:
                break  # 路径距离递增，更远的也超射程
            return actions.use_resource(ResourceType.INTEL, nxt)
        return None

    # ---- 绕路做任务（M7）----

    def _task_detour_target(self, world, me, gm, node, terminal):
        """按档位（§5.1 行1/2）在预算内选一处绕路任务点，并过 §3.3 分数质量地板 ΔEV。

        与门：0≤extra≤档位绕路上限 且 `_can_afford`（时间地板）且
        `net_score_delta ≥ 档位 ΔEV 阈值`（分数地板）。任一不过则跳过该候选。
        这防止 AGGRESSIVE 放宽绕路上限后重演 839cfc9 的过度贪任务/烧鲜度败局。
        """
        tuning = self.tuning
        if (me.task_score or 0) >= tuning.task_seek_target or not terminal:
            return None
        pid = self.ctx.player_id
        _, direct = gm.time_optimal_path(node, terminal)
        if direct == _INF:
            return None
        best, best_extra = None, _INF
        for t in world.active_tasks():
            tn = t.get("nodeId")
            if not tn or tn == node:
                continue
            if t.get("taskTemplateId") in config.SKIP_TASK_TEMPLATES:
                continue
            prot = t.get("protectionPlayerId") or 0
            if prot and prot != pid:
                continue
            owner = t.get("ownerPlayerId") or 0
            if owner and owner != pid:
                continue
            _, c1 = gm.time_optimal_path(node, tn)
            _, c2 = gm.time_optimal_path(tn, terminal)
            if c1 == _INF or c2 == _INF:
                continue
            pr = t.get("processRound", 0) or 0
            extra = (c1 + pr + c2) - direct
            if not (0 <= extra <= tuning.task_detour_max_extra_frames) or extra >= best_extra:
                continue
            if not self._can_afford(world, gm, node, extra, terminal):
                continue
            task_pts = t.get("score", 0) or 0
            if self._detour_net_delta(me, task_pts, extra) < tuning.action_min_net_score:
                continue  # 净收益不足（分数质量地板）——不为它绕路
            best, best_extra = tn, extra
        return best

    def _detour_net_delta(self, me, task_pts, extra_frames):
        """绕路做任务的投影净收益 ΔEV（§3.3）。以本方投影为基线，计入额外耗时与鲜度损耗。

        缺投影或直达都无法交付时返回 -inf（拒绝绕路——连直达都交不了，绕路更无意义）。
        """
        mp = self.projection_bus.my_projection if self.projection_bus else None
        if mp is None or mp.deliver_frame is None:
            return _INF * -1
        extra_loss = extra_frames * AVG_FRESHNESS_LOSS_PER_FRAME
        return net_score_delta(
            mp.deliver_frame, mp.projected_task_score, mp.projected_good_fruit,
            mp.projected_freshness,
            penalty=me.penalty_score or 0,
            duration=self.ctx.duration_round or 600,
            extra_task_score=task_pts, extra_frames=extra_frames,
            extra_freshness_loss=extra_loss)

    # ---- 悬赏机会主义（M8 Layer 2 / P2 §5.2）----

    def _maybe_bounty(self, world, me, gm, node, terminal):
        """顺路/近路低代价破对手卡拿破关悬赏（§5.2）。

        与门：对手有效设卡 + `_plan_attack` 低成本可破（保交付好果下限）+
        额外帧≤`BOUNTY_MAX_EXTRA_FRAMES` 且过 `_can_afford`（时间地板）+
        `net_score_delta ≥ BOUNTY_MIN_NET_SCORE`（分数地板：计悬赏得分 − 烧好果 − 额外耗时/鲜度）。
        领先(CONSERVATIVE)锁胜、或 RUSH 保交付时不追悬赏；不为悬赏大幅改道。

        相邻悬赏节点 → `BREAK_GUARD`；否则沿不含目标的阻塞感知路径 `MOVE` 一步靠近。
        """
        if world.is_rush or not terminal or self.tuning.mode == RiskMode.CONSERVATIVE:
            return None
        mp = self.projection_bus.my_projection if self.projection_bus else None
        if mp is None or mp.deliver_frame is None:
            return None
        blocked_all = self._blocked_nodes(world, me)
        _, direct = gm.time_optimal_path(node, terminal, blocked=blocked_all)
        if direct == _INF:
            _, direct = gm.time_optimal_path(node, terminal)
        if direct == _INF:
            return None

        best = None  # (delta, action)
        for b in world.bounties:
            if not b.get("active") or b.get("completed") or (b.get("winnerPlayerId") or 0):
                continue
            bn = b.get("nodeId")
            if not bn or bn == node:
                continue
            ns = world.node(bn)
            owner = ns.active_guard_owner() if ns else None
            if not owner or owner == me.team_id:  # 只破对手的有效设卡才拿到悬赏
                continue
            plan = self._plan_attack(world, me, ns)
            if plan is None:  # 低成本破不了（防守值过高或好果保不住下限）
                continue
            blocked = blocked_all - {bn}   # 目标悬赏卡视为可进入，其它阻塞仍绕行
            path_to, c1 = gm.time_optimal_path(node, bn, blocked=blocked)
            if not path_to or len(path_to) < 2 or c1 == _INF:
                continue
            _, c2 = gm.time_optimal_path(bn, terminal, blocked=blocked)
            if c2 == _INF:
                continue
            extra = (c1 + c2) - direct
            if extra > config.BOUNTY_MAX_EXTRA_FRAMES:
                continue
            wait = extra if extra > 0 else 0
            if not self._can_afford(world, gm, node, wait, terminal):
                continue
            raw = b.get("rewardScore", 0) or 0
            delta = net_score_delta(
                mp.deliver_frame, mp.projected_task_score, mp.projected_good_fruit,
                mp.projected_freshness, penalty=me.penalty_score or 0,
                duration=self.ctx.duration_round or 600,
                extra_bounty=raw, extra_frames=wait, good_fruit_burned=plan[0],
                extra_freshness_loss=wait * AVG_FRESHNESS_LOSS_PER_FRAME)
            if delta < config.BOUNTY_MIN_NET_SCORE:
                continue
            if len(path_to) == 2:            # 已相邻 → 破卡拿悬赏
                g, bad, bo = plan
                action = actions.break_guard(bn, good_fruit=g, bad_fruit=bad,
                                             rush_tactic=(Action.BREAK_ORDER if bo else None))
            else:                            # 未相邻 → 顺路靠近一步
                action = actions.move(path_to[1])
            if best is None or delta > best[0]:
                best = (delta, action)
        return [best[1]] if best else None

    # ---- 小分队（M7：防御性预清障/削弱 + 探路宫门）----

    def _maybe_squad(self, world, me, gm, node, terminal):
        if world.is_rush:
            return None  # RUSH 禁止新派小分队
        avail = me.squad_available or 0
        if avail >= 2:
            blk = self._first_block_ahead(world, me, gm, node, terminal)
            if blk:
                nid, kind = blk
                key = (nid, kind)
                if key not in self._squad_sent:
                    self._squad_sent.add(key)
                    if kind == "obstacle":
                        return actions.squad_clear(nid)
                    if kind == "guard":
                        return actions.squad_weaken(nid)
        return self._maybe_scout_gate(world, me, gm, node)

    def _first_block_ahead(self, world, me, gm, node, terminal):
        if not terminal:
            return None
        path, _ = gm.time_optimal_path(node, terminal)
        if not path:
            return None
        for i, nid in enumerate(path):
            if i < config.SQUAD_AHEAD_MIN_HOPS:
                continue  # 太近交给主车队突破（小分队延迟落地来不及）
            ns = world.node(nid)
            if ns and ns.has_obstacle:
                return (nid, "obstacle")
            owner = ns.active_guard_owner() if ns else None
            if owner and owner != me.team_id:
                return (nid, "guard")
        return None

    def _maybe_scout_gate(self, world, me, gm, node):
        if self._gate_scout_sent or (me.squad_available or 0) < 1:
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

    # ---- 进攻干扰（M7，默认关闭）----

    def _maybe_set_guard(self, world, me, gm, node):
        if not config.ENABLE_OFFENSIVE or world.is_rush:
            return None
        n = gm.node(node)
        if not n or n.type != "KEY_PASS":
            return None
        ns = world.node(node)
        if ns and ns.guard and (ns.guard.get("defense", 0) or 0) > 0:
            return None
        if me.good_fruit < 20:  # 保留充足好果用于交付得分
            return None
        return actions.set_guard(node, extra_good_fruit=1)

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

    def _extract_main(self, result):
        for a in result:
            act = a.get("action", "")
            if act.startswith("SQUAD_") or act == Action.WINDOW_CARD:
                continue
            return a
        return None

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
        """做完 extra_frames 读条后仍能按时交付（含未验核时的验核耗时）。"""
        if terminal is None:
            return True
        est = self._deliver_estimate(world, world.me, gm, node, terminal)
        if est == _INF:
            return False
        end = (world.round or 0) + extra_frames + est + config.DELIVER_TIME_SAFETY_MARGIN
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
