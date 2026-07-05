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
  * 进攻干扰(智能门控，config.OFFENSIVE_ENABLED)：在对手必经的关键关隘种卡拖延对手(领先时回避悬赏)，
    并用小分队 SQUAD_REINFORCE 增援己方设卡(+2防守,不耗好果)。

策略与通信解耦：只依赖 core.WorldState / GameMap，不 import socket。
"""

import random

import config
from core import rules
from core.game_map import GameMap
from protocol import actions
from protocol.enums import Action, Card, PlayerState, ResourceType, Weather

_IDLE_LIKE = (PlayerState.IDLE, PlayerState.COST_BANKRUPT, None)
_MOVE_BUFF_TYPES = frozenset({ResourceType.FAST_HORSE, ResourceType.SHORT_HORSE, "RUSH_SPEED"})
_MOVE_BLOCK_CODES = frozenset({"MOVE_BLOCKED_BY_GUARD", "TARGET_NOT_REACHABLE",
                               "MOVE_EDGE_NOT_FOUND", "OBJECT_BUSY"})
# 任务类拒绝码：服务端判定条件不满足/任务不存在 → 拉黑 taskId 本局不再领取（防 129 次空转循环）。
_TASK_REJECT_CODES = frozenset({"TASK_REQUIREMENT_NOT_MET", "TASK_NOT_FOUND"})
# 主动作退避码：同帧同类冲突 / 状态不允许该动作 → 退避 1 帧让服务端状态推进（防反复撞同一动作）。
_ACTION_BACKOFF_CODES = frozenset({"INVALID_ACTION_CONFLICT", "MOVING_ACTION_FORBIDDEN",
                                    "RESTING_ACTION_FORBIDDEN"})
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
        # 任务模板查找表：taskTemplateId -> 模板属性（score/processRound/requiredResourceTypes/
        # requiredFreshness/processType）。用于动态判定任务可做性，地图变化时自动适配（不硬编码模板 ID）。
        self.task_template_map = {
            t.get("taskTemplateId"): t for t in (self.task_templates or []) if t.get("taskTemplateId")
        }
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
        self._cooldown = {}          # nodeId -> 拉黑截止回合（MOVE 阻塞拒绝反馈）
        self._last_main_action = None
        self._last_window_cid = None  # 上一帧出过的窗口 contestId（窗口拒绝归因）
        self._task_blacklist = set()  # taskId 被服务端拒绝(TASK_REQUIREMENT_NOT_MET/TASK_NOT_FOUND)，本局不再领取
        self._node_busy_until = {}    # nodeId -> 拉黑截止回合（CLAIM_RESOURCE/PROCESS 撞 OBJECT_BUSY）
        self._abstain_contests = {}   # contestId -> 弃权截止回合（WINDOW_DRAW_RETRY_LIMIT）
        self._action_block_until = {} # 主车队动作类型 -> 退避截止回合（INVALID_ACTION_CONFLICT 等）
        self._squad_sent = set()     # (nodeId, kind) 已派出的小分队目标，避免重复
        self._reinforced_guards = set()  # 已增援过的己方设卡节点，避免重复消耗人手
        self._offensive_guard_node = None  # 本节点已种过进攻卡：防服务端忽略/拒绝 SET_GUARD 时反复重发卡死
        self._window_played = {}     # contestId -> {roundIndex: 我方该拍出的牌}，避免同拍重复提交 + 决胜拍预判
        self._horse_planned_for_speed = False  # 本帧马是否已被加速占用（防窗口 QIANG 同帧双扣马）
        self.last_deliver_estimate = None  # 上一帧交付估值（供日志 Budget 事件，分析预算漂移）

    def decide(self, world):
        me = world.me
        gm = self.ctx.game_map
        if me is None or gm is None:
            return []

        node = me.current_node_id
        self._horse_planned_for_speed = False  # 每帧重置：马匹预算按帧结算
        self._apply_rejection_feedback(world)
        self._update_process_memory(world, me, node)
        terminal = gm.terminal_nodes[0] if gm.terminal_nodes else None
        gate = gm.gate_node

        result = []
        try:
            if me.delivered or me.state == PlayerState.DELIVERED:
                result = []
                return result
            # 主车队动作（按状态产出）：移动中/主动等待中续行；空闲态主计划；其余状态(CONTESTING/
            # PROCESSING/VERIFYING/RESTING/FORCED_PASSING)不产出主动作，交给服务端继续推进。
            main = []
            if me.state in (PlayerState.MOVING, PlayerState.WAITING):
                main = self._keep_moving(world, me, gm, node, terminal, gate)
            elif me.state in _IDLE_LIKE:
                main = self._plan(world, me, gm, node, terminal, gate)
            # 窗口出牌（独立动作类别）：与本帧主车队动作可同帧提交，不再因出牌而丢弃续行/主动作
            # （任务书§4.1：不同类别不互相占用额度）。PASS 守方被动参战时尤其需要边出牌边推进。
            card = self._window_card(world, me)
            # 小分队（独立动作类别）：移动中/等待中/空闲时可与主动作、窗口牌同帧提交。
            squad = None
            if me.state in _IDLE_LIKE or me.state in (PlayerState.MOVING, PlayerState.WAITING):
                squad = self._maybe_squad(world, me, gm, node, terminal)
            result = list(main) + ([card] if card else []) + ([squad] if squad else [])
            result = self._dedup_actions(result)  # 协议§4.1：每类动作≤1，防御性兜底
            return result
        finally:
            self._prev_state = me.state
            self._last_main_action = self._extract_main(result)
            self._last_window_cid = next(
                (a.get("contestId") for a in result
                 if a.get("action") == Action.WINDOW_CARD),
                None)
            # 缓存交付估值供日志 Budget 事件（_can_afford 内部已多次调用 _deliver_estimate，
            # 这里再算一次代价可忽略；异常或无 terminal 时为 None，日志侧跳过）。
            try:
                if me is not None and terminal is not None:
                    self.last_deliver_estimate = self._deliver_estimate(
                        world, me, gm, me.current_node_id, terminal)
                else:
                    self.last_deliver_estimate = None
            except Exception:
                self.last_deliver_estimate = None

    # ---- 主计划（空闲态，在节点）----

    def _keep_moving(self, world, me, gm, node, terminal, gate):
        """处于移动中/主动等待中时保证持续前进，绝不空等卡死。

        - 值得加速且无移动增益 → 用一次马（USE_RESOURCE）。**协议 §4.1：每帧最多 1 个主车队动作**，
          USE_RESOURCE 与 MOVE 同属主车队动作，同帧并发其一必被 `INVALID_ACTION_CONFLICT` 拒绝
          （Iter18 曾误判二者不同类别而并发 `[horse, MOVE]`，0705 真机 37/37 拒绝循环、201 次冲突
          即此所致）。故用马本帧仅发 `[horse]`：服务端接受 USE_RESOURCE、马增益落地，下帧起
          `_maybe_horse` 因 `_has_move_buff` 返回 None 而续行 MOVE——至多 1 帧"读条"代价，不构成
          Iter8 的 park 死循环（死循环根因是"从不发 MOVE"，这里每帧仍发 MOVE 或一次马后即恢复 MOVE）。
        - 有在途目标 → 重发 MOVE 到当前目标节点续行（协议允许，不改道、不清进度）。
        - 无在途目标（已在节点却被报为等待）→ 按节点空闲重新规划。
        """
        horse = self._maybe_horse(world, me, gm, terminal)
        if horse:
            self._horse_planned_for_speed = True  # 通知窗口出牌：本帧马已被加速占用
            return [horse]
        if me.next_node_id:
            return [actions.move(me.next_node_id)]
        return self._plan(world, me, gm, node, terminal, gate)

    def _plan(self, world, me, gm, node, terminal, gate):
        rescue = self._freshness_rescue(world, me)
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
                    # 破关令绑定验核：RUSH 且未用急策 且鲜度充足(不会改用护果令) 且有≥2坏果(免费支付)
                    # 时绑定 BREAK_ORDER，验核 -3 帧（最低3）。鲜度充足时疾行令/护果令均不会触发，
                    # 急策额度否则会被浪费；坏果在终点前已无攻坚用途，转为减时收益（§6.5）。
                    bo = self._break_order_for_verify(world, me)
                    return [actions.verify_gate(rush_tactic=(Action.BREAK_ORDER if bo else None))]
                return self._opportunistic(world, me, gm, node, terminal) or []
            return self._advance(world, me, gm, node, terminal, terminal)

        if node in gm.process_nodes and not self._processed_here:
            if not self._is_node_busy(world, node):
                return [actions.process()]
            # 节点处理撞 OBJECT_BUSY → 拉黑期内跳过，落到下方推进/续行

        intel = self._maybe_intel(world, me, gm, node, terminal)
        if intel:
            return [intel]

        rp = self._maybe_rush_protect(world, me)
        if rp:
            return [rp]

        # at-node 收益（任务/资源领取）：任务/马领取受 _can_afford 自门控（告急时自动拒），
        # 仅冰鉴领取刻意豁免（2 帧 < 1 篓好果转坏的 3.6 分损失，且冰鉴是交付鲜度保险）。
        # 拒绝循环已由 P0 黑名单/P1 去重根治，此处不再因告急禁用 at-node 领取。
        opp = self._opportunistic(world, me, gm, node, terminal)
        if opp:
            return opp

        guard = self._maybe_offensive_guard(world, me, gm, node, terminal)
        if guard:
            return [guard]

        panic = self._delivery_panicking(world, me, gm, node, terminal)
        # 后期(≥RUSH_PREPOSITION_ROUND)且未验核：直奔宫门，确保 RUSH 触发时已在 S14 附近，
        # 避免 r450→r492 的 42 帧验核空隙（真机慢局用时分损失根因）。此时不再绕路做任务。
        # 交付告急时无论帧数都先去宫门验核（未验核则到终点也交付不了）。
        route_dst = self._late_route_target(world, me, gate, terminal)
        if panic and not me.verified and gate and gate != terminal:
            route_dst = gate
        if route_dst == gate:
            return self._advance(world, me, gm, node, gate, terminal)
        # 绕路收集冰鉴（鲜度优先）：投影交付鲜度不足且冰鉴节点在合理绕路范围内时，先绕去收集。
        # 冰鉴 +10 为交付前永久偏移，2 个叠加 +20 可把 80 阈值延后到交付之后——以额外帧换鲜度分+好果分。
        # 置于任务绕路之前：鲜度是交付质量硬约束，任务绕路其次。
        # 交付告急或 RUSH 阶段禁用一切绕路（保交付优先）：RUSH 是终局冲刺，绕路危及交付（P3a）。
        if panic or world.is_rush:
            dst = terminal
        else:
            dst = (self._ice_box_detour_target(world, me, gm, node, terminal)
                   or self._task_detour_target(world, me, gm, node, terminal)
                   or terminal)
        if dst:
            return self._advance(world, me, gm, node, dst, terminal)
        return []

    def _delivery_panicking(self, world, me, gm, node, terminal):
        """交付告急：按当前路线估算已无法按时交付（est + 通用余量 > 剩余帧）。

        0705 真机 35/37 触发 EST_OVER_BUDGET 但仍持续做 USE_RESOURCE/CLAIM_TASK/WINDOW 循环，
        致 17 场未交付。P0/P1 已消除循环，此为兜底——预算告警时不再为小收益冒险，强制保交付。

        估算用 _deliver_estimate_pessimistic（计入途中已知阻塞的真实时间成本：障碍清障税、
        不可破敌卡的强制通行税、cooldown 节点绕行），与 _advance 实际"绕行 vs 突破"决策口径一致。
        旧版用乐观 _deliver_estimate（忽略阻塞）致密集阻塞下低估、迟触发告急——前方连续多个
        障碍/敌卡时，乐观估算认为尚早而继续绕路做任务，实际已来不及。
        """
        if terminal is None or (me.verified and node == terminal):
            return False
        est = self._deliver_estimate_pessimistic(world, me, gm, node, terminal)
        if est == _INF:
            return True  # 绕行与直行(含税)皆不可达 → 必然超时，按告急处理（强制突破）
        remaining = (self.ctx.duration_round or 600) - (world.round or 0)
        return est + config.DELIVER_TIME_SAFETY_MARGIN > remaining

    def _late_route_target(self, world, me, gate, terminal):
        """后期路由目标：未验核且进入 RUSH 前置窗口时返回宫门，否则返回终点。"""
        if (gate and terminal and gate != terminal
                and (world.round or 0) >= config.RUSH_PREPOSITION_ROUND
                and not me.verified):
            return gate
        return terminal

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
        # path_b：绕行（屏蔽障碍/敌方设卡/cooldown 节点）；path_t：直行但计入"交税通行"代价
        # （敌方设卡时间税、障碍清障税），用于准确权衡绕行 vs 就地突破（§6.3.2）。
        blocked = self._blocked_nodes(world, me)
        tax_fn = self._enter_cost_fn(world, me)
        path_b, cost_b = self._time_path(world, src, dst, blocked=blocked)
        path_t, cost_t = self._time_path(world, src, dst, enter_cost_fn=tax_fn)

        if path_b and len(path_b) > 1:
            # 绕行远比直行(含税)贵 → 直路下一跳就地突破（清障/攻坚/强制通行）。
            # RUSH 阶段用更紧阈值：终局冲刺优先就地突破保交付，避免绕路超时（P3b）。
            threshold = (config.REROUTE_VS_CLEAR_RUSH_EXTRA if world.is_rush
                         else config.REROUTE_VS_CLEAR_EXTRA)
            if path_t and len(path_t) > 1 and cost_b - cost_t > threshold:
                nxt = path_t[1]
                ns = world.node(nxt)
                blocked_by = (ns is not None and (ns.has_obstacle
                                or ns.active_guard_owner() not in (None, me.team_id)))
                if blocked_by and not self._is_cooldown(world, nxt):
                    # 障碍清障需 1 好果；好果不足则不走直路突破，改绕行
                    if ns.has_obstacle and me.good_fruit <= config.KEEP_GOOD_FRUIT_MIN:
                        pass
                    else:
                        return self._breakthrough(world, me, gm, nxt, terminal)
            speed = self._rush_speed_warranted(world, me, gm, src, terminal)
            if speed:
                return [speed]
            return [actions.move(path_b[1])]

        # 无法绕行：沿直行最短路突破下一个阻塞节点
        if not path_t or len(path_t) < 2:
            return []
        return self._breakthrough(world, me, gm, path_t[1], terminal)

    def _time_path(self, world, src, dst, blocked=None, enter_cost_fn=None):
        """time_optimal_path 的天气+鲜度感知封装：套用当前生效天气通行倍率与鲜度权重。"""
        return self.ctx.game_map.time_optimal_path(
            src, dst, weather_type=world.active_weather_type(),
            blocked=blocked, enter_cost_fn=enter_cost_fn,
            freshness_weight=config.FRESHNESS_ROUTE_LAMBDA)

    def _enter_cost_fn(self, world, me):
        """返回 node_id -> 交税通行额外帧数 的回调，用于直行代价估算。

        - 障碍：清障 6 帧(有好果) / 强制通行 8 帧(无好果)
        - 敌方有效设卡：可攻坚则 0 帧(攻坚无处理帧) / 否则按强制通行时间税(§6.3.2)
        己方设卡、无阻挡节点返回 0。
        """
        gm = self.ctx.game_map
        # 路由代价估算与实际攻坚(_plan_attack)一致：RUSH 阶段未用急策时可绑破关令(+3)，
        # 避免高估直行代价、误绕远路（_can_break 保守不含 bo 会让 [best, best+3] 区间判为不可破）。
        bo_bonus = 3 if (world.is_rush and (me.rush_tactic_used_count or 0) == 0) else 0

        def tax(node_id):
            ns = world.node(node_id)
            if not ns:
                return 0
            if ns.has_obstacle:
                return 6 if me.good_fruit > config.KEEP_GOOD_FRUIT_MIN else rules.OBSTACLE_TIME_TAX
            owner = ns.active_guard_owner()
            if owner and owner != me.team_id:
                defense = (ns.guard or {}).get("defense", 0) or 0
                if self._can_break(me, defense, bo_bonus):
                    # §6.3.1：攻坚无额外处理帧，但消耗好果（交付分机会成本）。折算帧成本避免
                    # 路由把破卡当免费而过度偏好破卡——即便有便宜绕路也硬破浪费好果分。
                    return self._break_good_needed(defense, bo_bonus, me) * config.BREAK_GUARD_GOOD_FRAME_EQ
                return rules.guard_time_tax(self._node_kind(gm, node_id), defense)
            return 0
        return tax

    def _enter_cost_real_frames(self, world, me):
        """用于交付时间估算的 node_id -> 真实额外帧成本 回调。

        与 _enter_cost_fn 的关键区别：攻坚可破的敌方设卡此处按 0 帧计（§6.3.1 攻坚破卡无额外
        处理帧数，仅消耗好果），不把好果机会成本折算成帧——否则会高估交付时间、过度触发告急。
        不可破的敌卡按强制通行时间税(§6.3.2)计；障碍按清障 6 帧(有好果)/强制通行 8 帧(无好果)计。
        己方设卡、无阻挡节点、cooldown-only 节点返回 0（cooldown 节点物理可通行，仅曾被拒）。
        """
        gm = self.ctx.game_map
        bo_bonus = 3 if (world.is_rush and (me.rush_tactic_used_count or 0) == 0) else 0

        def tax(node_id):
            ns = world.node(node_id)
            if not ns:
                return 0
            if ns.has_obstacle:
                return 6 if me.good_fruit > config.KEEP_GOOD_FRUIT_MIN else rules.OBSTACLE_TIME_TAX
            owner = ns.active_guard_owner()
            if owner and owner != me.team_id:
                defense = (ns.guard or {}).get("defense", 0) or 0
                if self._can_break(me, defense, bo_bonus):
                    return 0  # 攻坚无额外处理帧，仅耗好果（交付时间不计）
                return rules.guard_time_tax(self._node_kind(gm, node_id), defense)
            return 0
        return tax

    def _break_good_needed(self, defense, bo_bonus, me):
        """攻坚该防守值预估需投入的好果数（坏果优先填充，每篓好果 2 攻坚值）。

        仅用于路由代价估算（_enter_cost_fn），非实际攻坚决策——实际投入由 _plan_attack 产出。
        """
        if defense <= 0:
            return 0
        bad_val = min(me.bad_fruit or 0, 2) * 3
        remaining = max(0, defense - bo_bonus - bad_val)
        return min(2, (remaining + 1) // 2)  # ceil(remaining/2)，单次攻坚好果上限 2

    def _can_break(self, me, defense, bo_bonus=0):
        """是否能在保留 KEEP_GOOD_FRUIT_MIN 好果的前提下攻破该防守值。

        bo_bonus：破关令额外攻坚值(+3)，仅在 RUSH 未用急策时计入（与 _plan_attack 一致），
        用于路由代价估算；实际攻坚决策仍由 _plan_attack 产出。
        """
        if defense <= 0:
            return True
        avail_good = max(0, me.good_fruit - config.KEEP_GOOD_FRUIT_MIN)
        best = 0
        for g in range(0, min(2, avail_good) + 1):
            for b in range(0, min(2, me.bad_fruit) + 1):
                best = max(best, g * 2 + b * 3 + bo_bonus)
        return best >= defense

    def _node_kind(self, gm, node_id):
        node = gm.node(node_id)
        if node is None:
            return "normal"
        if node_id == gm.gate_node:
            return "gate"
        if node.type == "KEY_PASS":
            return "key_pass"
        return "normal"

    def _verify_frames(self, world, me, gm):
        info = gm.process_nodes.get(gm.gate_node) if gm.gate_node else None
        base = (info.get("processRound") if info else 6) or 6
        if self._break_order_for_verify(world, me):
            return max(3, base - 3)  # 破关令使验核 -3 帧，最低 3（§6.5）
        return base

    def _break_order_for_verify(self, world, me):
        """宫门验核是否绑定破关令。

        条件：RUSH 阶段、本局未用过急策、鲜度≥护果令阈值(否则急策额度留给护果令保鲜)、
        坏果≥2(破关令坏果优先支付，不损耗交付好果分)。满足时白送 3 帧验核减时。
        """
        if not world.is_rush or (me.rush_tactic_used_count or 0) > 0:
            return False
        if me.freshness < config.RUSH_PROTECT_FRESHNESS_BELOW:
            return False
        return (me.bad_fruit or 0) >= 2

    def _deliver_estimate(self, world, me, gm, node, terminal):
        """从当前节点完成交付的估计帧数：路线到终点 + 未验核则加验核帧 + 少量缓冲（供 _can_afford）。

        路线耗时按当前生效天气估算（暴雨/山雾减速计入），不计入设卡/障碍税（保持乐观，假设途中
        就地突破；安全余量 DELIVER_TIME_SAFETY_MARGIN 吸收小幅偏差）。
        """
        if not terminal:
            return _INF
        _, travel = self._time_path(world, node, terminal)
        if travel == _INF:
            return _INF
        est = travel + 2
        if not me.verified:
            est += self._verify_frames(world, me, gm)
        return est

    def _deliver_estimate_pessimistic(self, world, me, gm, node, terminal):
        """悲观交付估算：计入途中已知阻塞的真实时间成本，用于 _delivery_panicking。

        取"绕行(path_b，屏蔽障碍/敌卡/cooldown)"与"直行含税(path_t，障碍清障税 + 不可破敌卡
        强制通行税)"两条路较小者——与 _advance 实际决策口径一致（advance 在 path_b/path_t 间
        择优突破或绕行）。可破敌卡在 path_t 中按 0 帧计（攻坚无额外处理帧），故不会因好果机会
        成本高估。两者皆不可达 → _INF（必然超时，告急强制突破）。

        区别于 _deliver_estimate（乐观，忽略阻塞，供 _can_afford 等预算门控使用，由
        DELIVER_TIME_SAFETY_MARGIN 吸收偏差）：告警场景需要"最坏也能到"的判定，故用悲观口径。
        """
        if not terminal:
            return _INF
        blocked = self._blocked_nodes(world, me)
        tax_fn = self._enter_cost_real_frames(world, me)
        _, cost_b = self._time_path(world, node, terminal, blocked=blocked)
        _, cost_t = self._time_path(world, node, terminal, enter_cost_fn=tax_fn)
        best = cost_b
        if cost_t < best:
            best = cost_t
        if best == _INF:
            return _INF
        est = best + 2
        if not me.verified:
            est += self._verify_frames(world, me, gm)
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

    def _is_node_busy(self, world, nid):
        """节点是否因 CLAIM_RESOURCE/PROCESS 撞 OBJECT_BUSY 而临时拉黑。"""
        return self._node_busy_until.get(nid, 0) > (world.round or 0)

    def _is_contest_abstained(self, world, cid):
        """窗口是否因 WINDOW_DRAW_RETRY_LIMIT 而本周期弃权。"""
        return cid is not None and self._abstain_contests.get(cid, 0) > (world.round or 0)

    def _is_action_blocked(self, world, act):
        """主动作类型是否因 INVALID_ACTION_CONFLICT 等而本帧退避（仅用于收益类动作，不阻断 MOVE/交付）。"""
        return act is not None and self._action_block_until.get(act, 0) > (world.round or 0)

    def _breakthrough(self, world, me, gm, nxt, terminal):
        ns = world.node(nxt)
        if ns and ns.has_obstacle:
            # 优先做清障任务(T04)：+30 任务分且清障，优于 CLEAR(耗 1 好果、0 分)。
            # 按协议 processType 判定（非模板 ID），地图变化自动适配。
            t_clear = self._find_clear_obstacle_task(world, nxt)
            if t_clear and self._can_afford(
                    world, gm, me.current_node_id, t_clear.get("processRound", 6) or 6, terminal):
                return [actions.claim_task(t_clear.get("taskId"))]
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

    def _find_clear_obstacle_task(self, world, node):
        """挂在指定障碍节点上的活跃清障任务(T04, processType=CLEAR_OBSTACLE)。"""
        for t in world.active_tasks():
            if t.get("taskId") in self._task_blacklist:
                continue
            if self._is_clear_obstacle_task(t) and t.get("nodeId") == node:
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

    # ---- 拒绝反馈（M7 + Iter20 全覆盖）----

    def _apply_rejection_feedback(self, world):
        """读上一帧 actionResults/events 的拒绝码，按码分类记忆，杜绝当帧重发同一被拒动作。

        0705 真机 37/37 拒绝循环根因：旧版只处理 PROCESS_REQUIRED 与 MOVE+移动阻塞码，对其余码
        （TASK_REQUIREMENT_NOT_MET / OBJECT_BUSY(非MOVE) / WINDOW_DRAW_RETRY_LIMIT /
        INVALID_ACTION_CONFLICT）完全裸奔 → 客户端每帧重发同一被拒动作至 600 帧（单场 CLAIM_TASK×142
        被拒 129、USE_RESOURCE×202 被拒 201、WINDOW_CARD×177 被拒 105），吃光帧预算致 17 场未交付。
        """
        codes = self._my_reject_codes(world)
        if not codes:
            return
        rnd = world.round or 0
        la = self._last_main_action
        la_act = la.get("action") if la else None
        for code in codes:
            if code == "PROCESS_REQUIRED":
                self._processed_here = False  # 强制在当前节点先完成固定处理
                continue
            # 移动阻塞（含 OBJECT_BUSY 的 MOVE 场景）：拉黑目标节点，路由绕行
            if code in _MOVE_BLOCK_CODES and la_act == Action.MOVE:
                tgt = la.get("targetNodeId")
                if tgt:
                    self._cooldown[tgt] = rnd + config.REJECT_BLOCK_ROUNDS
                continue
            # 任务被拒：拉黑 taskId 本局不再领取（镜像可做性与服务端不一致不会自愈，永久拉黑该实例）
            if code in _TASK_REJECT_CODES:
                if la_act == Action.CLAIM_TASK and la.get("taskId"):
                    self._task_blacklist.add(la.get("taskId"))
                continue
            # 资源领取/站点处理撞占用：节点级忙冷却（MOVE 的 OBJECT_BUSY 已由上面分支处理）
            if code == "OBJECT_BUSY":
                if la_act in (Action.CLAIM_RESOURCE, Action.PROCESS):
                    tgt = la.get("targetNodeId") or (world.me.current_node_id if world.me else None)
                    if tgt:
                        self._node_busy_until[tgt] = rnd + config.REJECT_BLOCK_ROUNDS
                continue
            # 窗口抽签重试上限：该窗口本周期仅弃权，不再出牌（防停在 DOCK 死磕 59 个窗口）
            if code == "WINDOW_DRAW_RETRY_LIMIT":
                if self._last_window_cid:
                    self._abstain_contests[self._last_window_cid] = rnd + config.WINDOW_ABSTAIN_ROUNDS
                continue
            # 同帧同类冲突 / 状态不允许：主动作退避 1 帧（P1 已杜绝并发，此为服务端状态机偶发兜底）
            if code in _ACTION_BACKOFF_CODES and la_act:
                self._action_block_until[la_act] = rnd + 1
                continue

    def _my_reject_codes(self, world):
        """上一帧本方收到的所有拒绝码（actionResults + ACTION_REJECTED/INVALID_ACTION 事件）。"""
        pid = self.ctx.player_id
        prev = (world.round or 0) - 1
        codes = []
        for r in world.action_results:
            if r.get("playerId") == pid and r.get("round") == prev and r.get("accepted") is False:
                c = r.get("errorCode")
                if c:
                    codes.append(c)
        for e in world.events:
            if e.get("type") in ("ACTION_REJECTED", "INVALID_ACTION"):
                p = e.get("payload") or {}
                if p.get("playerId") == pid and p.get("errorCode"):
                    codes.append(p.get("errorCode"))
        return codes

    # ---- 收益子策略（M4）----

    def _freshness_rescue(self, world, me):
        """冰鉴使用：鲜度 ≤ ICE_BOX_CAP_AVOID(90) 即用，使 +10 鲜度作为永久偏移存活到交付。

        核心认识（Iter15 真机归因 7/7 鲜度崩盘驱动）：鲜度损耗线性（每帧固定扣除），
        冰鉴 +10 是交付前的"永久偏移"——无论何时使用（交付前），最终鲜度都 +10
        （前提：不撞 100 上限）。故最优策略 = 持有冰鉴时尽快在鲜度 ≤90 时使用：
        - ≤90 用：+10 不撞 100 上限（无浪费），偏移叠加到交付 → 鲜度分 +1.8/点。
        - >90 不用：+10 撞 100 上限造成鲜度浪费，且抢走破关令验核额度。

        用满 2~3 个冰鉴（路线经过 S03/S06/S07）可叠加 +20~30 偏移：既涨交付鲜度分
        （+18~36），又可能把 80 阈值首次低于延后到交付之后（+3.6 好果分）。

        旧"仅近阈值(≤7)使用"逻辑过保守：鲜度 89（距 80 阈值 9>7）不用，
        导致整局仅用 1 个冰鉴，余量闲置——此为本轮主要失分点。

        §3.3.1：冰鉴只提高当前鲜度，不重置已触发的好果转坏记录；§3.2.1：阈值首次低于触发（一次）。
        """
        if me.resource_count(ResourceType.ICE_BOX) <= 0:
            return None
        if self._is_action_blocked(world, Action.USE_RESOURCE):
            return None  # 上一帧 USE_RESOURCE 被 INVALID_ACTION_CONFLICT 等拒，本帧退避
        f = me.freshness
        if 0 < f <= config.ICE_BOX_CAP_AVOID:
            return actions.use_resource(ResourceType.ICE_BOX)
        return None

    def _task_score_capped(self, me):
        """皇榜任务分是否已达 180 封顶（再做任何普通皇榜任务都不再增分）。

        taskScore 字段为普通皇榜任务基础分累计；最终任务分 = min(180, 累计 + 里程碑)
        （§7.2/§5）。基础分累计 ≥130 时 130+50=180 封顶，此后再做任务：任务分/送达分/
        用时分三项均不再增长，只徒增处理帧(延误交付→用时分下降)与鲜度损耗(鲜度分下降)，
        为净负收益，故应停止。
        """
        base = me.task_score or 0
        return base + rules.task_milestone_bonus(base) >= 180

    # ---- 任务可做性判定（动态，基于协议模板属性，不硬编码模板 ID）----

    def _template_of(self, task):
        return self.ctx.task_template_map.get(task.get("taskTemplateId"), {}) or {}

    def _is_clear_obstacle_task(self, task):
        """T04 清障任务：processType == CLEAR_OBSTACLE（按协议字段判定，非模板 ID）。

        优先读任务实例的 processType（inquire.tasks 携带）；缺失时回退到模板 processType。
        """
        if task.get("processType") == "CLEAR_OBSTACLE":
            return True
        return self._template_of(task).get("processType") == "CLEAR_OBSTACLE"

    def _task_required_resources(self, task):
        """任务要求持有的资源类型列表（来自模板 requiredResourceTypes，如 T06 要求马）。"""
        tpl = self._template_of(task)
        # 模板未声明时回退到任务实例（部分下发会把要求挂在实例上）
        return list((tpl.get("requiredResourceTypes") or task.get("requiredResourceTypes") or []))

    def _task_required_freshness(self, task):
        tpl = self._template_of(task)
        f = tpl.get("requiredFreshness")
        if f is None:
            f = task.get("requiredFreshness")
        return f or 0

    def _task_at_node(self, task, node, gm):
        """任务是否可在当前节点处理（§5.2）。

        普通任务：必须停在 task.nodeId。
        T04 清障任务：可在障碍节点本身或其相邻节点处理（"从相邻节点完成 T04...主车队仍停在原节点"）。
        """
        tn = task.get("nodeId")
        if not tn:
            return False
        if tn == node:
            return True
        if self._is_clear_obstacle_task(task) and gm is not None:
            return tn in gm.neighbors(node)
        return False

    def _task_claimable_by_me(self, task, pid):
        """保护期/归属是否允许本方领取（§5.4 任务争抢）。"""
        prot = task.get("protectionPlayerId") or 0
        if prot and prot != pid:
            return False
        owner = task.get("ownerPlayerId") or 0
        if owner and owner != pid:
            return False
        return True

    def _can_spend_required_resources(self, me, task):
        """是否能满足任务所需资源（如 T06 需消耗 1 马）。

        马类(FAST_HORSE/SHORT_HORSE)任一持有≥1 即可（任务书：消耗 1 个快马或短程马，二选一）；
        30 任务分远大于单匹马的移速收益（约 1~2 用时分），故只要持有就愿意消耗，不再为保马而放弃任务分。
        其他资源要求持有对应数量（本玩法任务仅要求"持有"，CLAIM_TASK 时由服务端结算消耗）。
        """
        req = self._task_required_resources(task)
        if not req:
            return True
        horses = {ResourceType.FAST_HORSE, ResourceType.SHORT_HORSE}
        horse_req = [r for r in req if r in horses]
        other_req = [r for r in req if r not in horses]
        for r in other_req:
            if me.resource_count(r) <= 0:
                return False
        if horse_req:
            if (me.resource_count(ResourceType.FAST_HORSE)
                    + me.resource_count(ResourceType.SHORT_HORSE)) <= 0:
                return False
        return True

    def _maybe_task(self, world, me, gm, node, terminal):
        # 任务分已封顶 180 时不再做新任务（见 _task_score_capped）。
        if self._task_score_capped(me):
            return None
        if self._is_action_blocked(world, Action.CLAIM_TASK):
            return None  # 上一帧 CLAIM_TASK 被冲突类拒绝，本帧退避
        pid = self.ctx.player_id
        for t in world.active_tasks():
            if t.get("taskId") in self._task_blacklist:
                continue  # 服务端已拒(TASK_REQUIREMENT_NOT_MET/TASK_NOT_FOUND)，本局不再领取
            if not self._task_at_node(t, node, gm):
                continue
            if not self._task_claimable_by_me(t, pid):
                continue
            if not self._can_spend_required_resources(me, t):
                continue
            rf = self._task_required_freshness(t)
            if rf and me.freshness < rf:
                continue
            pr = t.get("processRound", 0) or 0
            # 机会式(在节点)做任务无绕路成本，仅花处理帧；+30 分值得用与绕路同等的紧余量(15)释放预算。
            if not self._can_afford(world, gm, node, pr, terminal,
                                    safety_margin=config.TASK_DETOUR_SAFETY_MARGIN):
                continue
            return actions.claim_task(t.get("taskId"))
        return None

    def _maybe_claim(self, world, me, gm, node, terminal):
        ns = world.node(node)
        if ns is None:
            return None
        if self._is_node_busy(world, node):
            return None  # 该节点资源/处理撞 OBJECT_BUSY，临时拉黑期内不再领取
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
            if r == ResourceType.ICE_BOX:
                # 冰鉴领取豁免时间预算：2 帧成本远低于 1 篓好果转坏的 3.6 分损失（真机归因：
                # 7/7 跨 80 阈值 = 关键时刻无冰鉴，根因是领取被 _can_afford 拒或被移动竞争挤掉）。
                return actions.claim_resource(node, r)
            if self._can_afford(world, gm, node, config.RESOURCE_CLAIM_ROUND, terminal):
                return actions.claim_resource(node, r)
        return None

    def _maybe_horse(self, world, me, gm, terminal):
        if self._has_move_buff(me):
            return None
        if self._is_action_blocked(world, Action.USE_RESOURCE):
            return None  # 用马同属 USE_RESOURCE，退避期内不重发
        horse = None
        if me.resource_count(ResourceType.FAST_HORSE) > 0:
            horse = ResourceType.FAST_HORSE
        elif me.resource_count(ResourceType.SHORT_HORSE) > 0:
            horse = ResourceType.SHORT_HORSE
        if not horse or not self._far_from_terminal(gm, me.current_node_id, terminal):
            return None
        # 保留马给前方需消耗马的任务(如 T06)：30 任务分 >> 马的移速收益(~1 用时分)。
        # 若去路上还有可达的需马任务且任务分未封顶，则不把马用于加速，留给任务。
        if self._horse_requiring_task_ahead(world, me, gm, me.current_node_id, terminal):
            return None
        return actions.use_resource(horse)

    def _horse_requiring_task_ahead(self, world, me, gm, node, terminal):
        """去路上是否还有需消耗马的活跃任务(如 T06)且本方任务分未封顶。

        用于决定是否把马留给任务而非用于加速：T06 类任务 +30 分，远大于马的移速收益。
        仅检查任务节点是否在剩余路径上（含 T04 相邻一跳放宽），不深究预算/鲜度——
        保守保留即可，宁可多保留一匹马也不放弃 30 分。
        """
        if self._task_score_capped(me) or not terminal or gm is None:
            return False
        pid = self.ctx.player_id
        path, _ = self._time_path(world, node, terminal, blocked=self._blocked_nodes(world, me))
        if not path:
            path, _ = self._time_path(world, node, terminal)
        if not path:
            return False
        ahead = set(path)
        # T04 可从相邻节点处理，放宽一跳：障碍节点的相邻点在路径上也算
        for nb in list(ahead):
            ahead.update(gm.neighbors(nb))
        for t in world.active_tasks():
            if not self._task_claimable_by_me(t, pid):
                continue
            req = self._task_required_resources(t)
            if not req:
                continue
            if not any(r in (ResourceType.FAST_HORSE, ResourceType.SHORT_HORSE) for r in req):
                continue
            if t.get("nodeId") in ahead:
                return True
        return False

    def _maybe_rush_protect(self, world, me):
        if not world.is_rush or me.delivered or (me.rush_tactic_used_count or 0) > 0:
            return None
        if me.freshness < config.RUSH_PROTECT_FRESHNESS_BELOW:
            return actions.rush_protect()
        return None

    def _rush_speed_warranted(self, world, me, gm, node, terminal):
        if not world.is_rush or me.delivered or (me.rush_tactic_used_count or 0) > 0:
            return None
        if me.freshness < config.RUSH_PROTECT_FRESHNESS_BELOW:
            return None
        if self._has_any_horse(me) or not self._far_from_terminal(gm, node, terminal):
            return None
        return actions.rush_speed()

    # ---- 情报 INTEL（M7）----

    def _reduce_targets_on_route(self, world, me, gm, node, terminal):
        """本方去路上的固定处理点/宫门（可被探路减时且尚无己方标记），按路径顺序。"""
        if not terminal:
            return []
        path, _ = self._time_path(world, node, terminal, blocked=self._blocked_nodes(world, me))
        if not path or len(path) < 2:
            path, _ = self._time_path(world, node, terminal)
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
        path, _ = self._time_path(world, node, terminal, blocked=self._blocked_nodes(world, me))
        if not path or len(path) < 2:
            path, _ = self._time_path(world, node, terminal)
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
        if self._is_action_blocked(world, Action.USE_RESOURCE):
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
        # 任务分封顶(基础分≥130→180)后不再为任务绕路：超 130 的任务零分收益，只徒增用时与鲜度损耗。
        if not terminal or self._task_score_capped(me):
            return None
        pid = self.ctx.player_id
        blocked = self._blocked_nodes(world, me)
        _, direct = self._time_path(world, node, terminal)
        if direct == _INF:
            return None
        best, best_extra = None, _INF
        for t in world.active_tasks():
            tn = t.get("nodeId")
            if not tn or tn == node:
                continue
            if t.get("taskId") in self._task_blacklist:
                continue  # 服务端已拒，不再为其绕路
            if not self._task_claimable_by_me(t, pid):
                continue
            if not self._can_spend_required_resources(me, t):
                continue
            rf = self._task_required_freshness(t)
            if rf and me.freshness < rf:
                continue
            # T04 清障任务：障碍节点本身不可进入，目的点改为其可达相邻节点
            dst = tn
            if self._is_clear_obstacle_task(t):
                dst = self._clear_obstacle_approach(tn, gm, blocked)
                if dst is None:
                    continue  # 障碍节点无可达相邻点，无法处理
            if dst == node:
                continue  # 已在处理点，交给 _maybe_task 机会式领取，无需绕路
            _, c1 = self._time_path(world, node, dst, blocked=blocked)
            _, c2 = self._time_path(world, dst, terminal, blocked=blocked)
            if c1 == _INF or c2 == _INF:
                continue
            pr = t.get("processRound", 0) or 0
            extra = (c1 + pr + c2) - direct
            if not (0 <= extra <= config.TASK_DETOUR_MAX_EXTRA_FRAMES):
                continue
            if not self._freshness_allows(extra, me):
                continue
            # 按分值/额外帧的性价比排序（同分时取额外帧最小）；任务分 +score 远大于用时小成本
            score = t.get("score", 30) or 30
            key = extra / max(1, score)
            if key < best_extra and self._can_afford(
                    world, gm, node, extra, terminal, safety_margin=config.TASK_DETOUR_SAFETY_MARGIN):
                best, best_extra = dst, key
        return best

    def _clear_obstacle_approach(self, obstacle_node, gm, blocked):
        """T04 清障任务的处理站位：障碍节点的相邻节点中，不在 blocked 集合且距起点最近者。

        §5.2：T04 可在障碍节点或相邻节点处理。障碍节点本身不可 MOVE 进入，故绕路时选相邻节点。
        """
        if gm is None:
            return None
        best, best_dist = None, _INF
        for nb in gm.neighbors(obstacle_node):
            if nb in blocked:
                continue
            return nb  # 任一可达相邻点即可；具体距离由调用方 _time_path 计算
        return None

    def _freshness_allows(self, extra_frames, me):
        """绕路/读条额外耗时是否会过度损耗鲜度：预计鲜度跌破地板则放弃（保交付鲜度分）。"""
        if extra_frames <= 0:
            return True
        projected = me.freshness - extra_frames * config.FRESHNESS_LOSS_ASSUME
        return projected >= config.FRESHNESS_DETOUR_FLOOR

    def _ice_box_detour_target(self, world, me, gm, node, terminal):
        """绕路去冰鉴节点收集冰鉴：以额外帧换鲜度（用户优先鲜度诉求）。

        触发条件（全部满足）：
        - 已持冰鉴 < ICE_BOX_DETOUR_KEEP(2)：达到即不再绕。
        - 投影交付鲜度（含已持冰鉴 +10/个）< ICE_BOX_DETOUR_PROJECTED_BELOW(85)：鲜度充足时不牺牲用时分。
        - 存在冰鉴节点在 ICE_BOX_DETOUR_MAX_EXTRA_FRAMES(60) 绕路范围内、净鲜度收益
          (冰鉴 +10 − 绕路额外损耗) ≥ ICE_BOX_DETOUR_NET_MIN(6)、且时间预算允许。

        价值依据：冰鉴 +10 为交付前永久偏移（线性损耗，§3.3.1 不重置已触发记录）。
        竞技地图冰鉴在 S03/S06/S07，最短路 S02→S04→S05→S09 不经过；S02→S03→S07→S09 官道替代路
        顺路收 2 个冰鉴（+20 偏移），把 80 阈值延后到交付之后（+3.6 好果分 + 鲜度分）。
        净收益过滤排除山路绕路（S06：S01→S06 山路 0.07 损耗，净收益 <6 被排除），且官道绕路保留
        下游任务节点（S09 等），避免"绕冰鉴丢任务"的反噬。
        """
        if not terminal:
            return None
        have = me.resource_count(ResourceType.ICE_BOX)
        if have >= config.ICE_BOX_DETOUR_KEEP:
            return None
        remaining = self._deliver_estimate(world, me, gm, node, terminal)
        if remaining >= _INF:
            return None
        # 投影交付鲜度：当前鲜度 + 已持冰鉴未来 +10/个 − 剩余帧损耗
        projected = me.freshness + have * 10 - remaining * config.FRESHNESS_LOSS_ASSUME
        if projected >= config.ICE_BOX_DETOUR_PROJECTED_BELOW:
            return None
        direct_path, direct_cost = self._time_path(world, node, terminal)
        if direct_cost == _INF or not direct_path:
            return None
        direct_loss = self._path_freshness_loss(world, direct_path)
        best, best_extra = None, _INF
        for nid, ns in world.node_states.items():
            if nid == node or not ns.resource_available(ResourceType.ICE_BOX):
                continue
            p1, c1 = self._time_path(world, node, nid)
            p2, c2 = self._time_path(world, nid, terminal)
            if c1 == _INF or c2 == _INF or not p1 or not p2:
                continue
            extra = c1 + config.RESOURCE_CLAIM_ROUND + c2 - direct_cost
            if extra <= 0 or extra > config.ICE_BOX_DETOUR_MAX_EXTRA_FRAMES:
                continue
            # 净鲜度收益 = 冰鉴 +10 偏移 − 绕路额外鲜度损耗（排除山路等高损耗绕路）
            via_loss = self._path_freshness_loss(world, p1[:-1] + p2)
            net = 10 - (via_loss - direct_loss)
            if net < config.ICE_BOX_DETOUR_NET_MIN:
                continue
            if extra < best_extra and self._can_afford(
                    world, gm, node, extra, terminal, safety_margin=config.DELIVER_TIME_SAFETY_MARGIN):
                best, best_extra = nid, extra
        return best

    def _path_freshness_loss(self, world, path):
        """估算路径总鲜度损耗：∑ 单边帧数 × 路线损耗 × 天气鲜度系数（当前天气近似）。"""
        if not path or len(path) < 2:
            return 0.0
        gm = self.ctx.game_map
        wtype = world.active_weather_type()
        wcoef = rules.FRESHNESS_WEATHER_COEF.get(wtype, 1.0) if wtype else 1.0
        total = 0.0
        for i in range(len(path) - 1):
            e = gm.edge_between(path[i], path[i + 1])
            if e is None:
                continue
            wmult = rules.weather_move_multiplier(e.route_type, wtype)
            frames = rules.frames_on_edge(e.distance, e.route_type, weather_mult=wmult)
            total += frames * rules.route_freshness_loss(e.route_type) * wcoef
        return total

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
            elif config.SQUAD_REINFORCE_ENABLED:
                # 无前方阻塞需预清时，对己方有效设卡增援(+2防守,不耗好果)
                r = self._maybe_reinforce(world, me, gm)
                if r:
                    return r
        return self._maybe_scout_gate(world, me, gm, node)

    def _first_block_ahead(self, world, me, gm, node, terminal):
        if not terminal:
            return None
        path, _ = self._time_path(world, node, terminal)
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
        _, frames = self._time_path(world, node, gate)
        if frames == _INF or frames < config.GATE_SCOUT_MIN_FRAMES or frames > config.GATE_SCOUT_MAX_FRAMES:
            return None
        self._gate_scout_sent = True
        return actions.squad_scout(gate)

    # ---- 进攻干扰（M7+：智能设卡 + 小分队增援）----

    def _node_max_defense(self, gm, node_id):
        return rules.NODE_MAX_DEFENSE.get(self._node_kind(gm, node_id), 6)

    def _own_active_guards(self, world, me):
        """本方当前有效设卡列表 [(nodeId, NodeState)]（用于名额计数与增援选点）。"""
        out = []
        for nid, ns in world.node_states.items():
            if ns.active_guard_owner() == me.team_id:
                out.append((nid, ns))
        return out

    def _am_leading(self, world, me):
        """本方公开总分是否严格领先对手（用于悬赏风险回避，§6.3.3）。"""
        opp = world.opponent
        if opp is None:
            return False
        return (me.total_score or 0) > (opp.total_score or 0)

    def _opp_will_pass(self, world, opp, gm, node, terminal):
        """对手是否尚未越过本节点、且本节点在其前往终点的最短路上。

        用对手当前位置到终点的 time_optimal 路径判断；对手已在本节点/已越过(不在前向路径)→False。
        无法计算路径时，关键关隘作为共享咽喉保守视为会经过。
        """
        src = opp.current_node_id
        if not src or src == terminal or src == node:
            return False
        path, _ = self._time_path(world, src, terminal, blocked=self._blocked_nodes(world, world.me))
        if not path:
            path, _ = self._time_path(world, src, terminal)
        if not path:
            # 无法计算对手路径时不种卡：真机归因 S10 反噬案即因不确信仍种卡导致纯成本。
            return False
        return node in path

    def _maybe_offensive_guard(self, world, me, gm, node, terminal):
        """智能进攻设卡：在对手必经的关键关隘种卡拖延对手。

        门控（全部满足才种卡，交付优先为硬约束）：
        - 总开关开、非RUSH、未交付；
        - 当前节点为关键关隘(KEY_PASS)、且无任何有效设卡占用；
        - 己方有效设卡数 < 2（规则上限，避免新卡挤掉旧卡浪费成本）；
        - _can_afford(设卡4帧)：种卡不耽误按时交付；
        - 投入后好果 ≥ OFFENSIVE_GOOD_FRUIT_KEEP（保交付好果分）；
        - 对手未交付/未退赛且本节点在其前往终点的最短路上（尚未越过此点）；
        - 预期拖延对手帧数(forced_pass 时间税) ≥ OFFENSIVE_MIN_OPP_DELAY；
        - 悬赏风险：本方总分领先时回避(OFFENSIVE_LEAD_SKIP)，防给落后对手送破关悬赏(§6.3.3)。
        """
        if not config.OFFENSIVE_ENABLED or world.is_rush or me.delivered or terminal is None:
            return None
        n = gm.node(node)
        if n is None or n.type != "KEY_PASS":
            return None
        if node == self._offensive_guard_node:
            return None  # 本节点已种过卡：防服务端忽略/拒绝 SET_GUARD 时反复重发卡死（真实败局模式）
        ns = world.node(node)
        if ns and ns.active_guard_owner() is not None:
            return None  # 已有有效设卡占用（己方/敌方），新增不生效
        if len(self._own_active_guards(world, me)) >= 2:
            return None
        if not self._can_afford(world, gm, node, config.SET_GUARD_PROCESS_FRAMES, terminal):
            return None
        extra = config.OFFENSIVE_EXTRA_GOOD
        if me.good_fruit - extra < config.OFFENSIVE_GOOD_FRUIT_KEEP:
            return None
        opp = world.opponent
        if opp is None or opp.delivered or opp.retired:
            return None
        if not self._opp_will_pass(world, opp, gm, node, terminal):
            return None
        defense = rules.guard_defense(extra, self._node_max_defense(gm, node))
        if rules.guard_time_tax(self._node_kind(gm, node), defense) < config.OFFENSIVE_MIN_OPP_DELAY:
            return None
        if config.OFFENSIVE_LEAD_SKIP and self._am_leading(world, me):
            return None
        self._offensive_guard_node = node  # 记录：本节点已种卡，离开前不再重发
        return actions.set_guard(node, extra_good_fruit=extra)

    def _maybe_reinforce(self, world, me, gm):
        """对仍在生效、防守值未顶满的己方设卡增援 +2（每卡只增援一次，省人手；§6.2.1/小分队§5.3）。

        增援不耗好果、不占主车队动作，仅耗 2 小分队人手；选防守缺口最大者优先顶满。
        """
        best, best_deficit = None, 0
        for nid, ns in self._own_active_guards(world, me):
            if nid in self._reinforced_guards:
                continue
            defense = (ns.guard or {}).get("defense", 0) or 0
            deficit = self._node_max_defense(gm, nid) - defense
            if deficit > 0 and (best is None or deficit > best_deficit):
                best, best_deficit = nid, deficit
        if best is None:
            return None
        self._reinforced_guards.add(best)
        return actions.squad_reinforce(best)

    # ---- 窗口出牌（反应式 3 拍）----

    # 牌克制矩阵（§5.4.4）：BEATS[对手牌] = 能克制它的牌，按"真实机会成本从低到高"排序。
    # BING/XIAN 各胜 2 张为强牌；唯一克制关系：XIAN 仅被 QIANG 克，BING 仅被 XIAN 克。
    # 反制对手 YAN 时：BING(耗护卫点)优先于 XIAN(耗好果+要求鲜度≥80)。护卫点 4 点不恢复、
    # 唯一用途是 BING，机会成本低；好果直接换交付分(≈1.8/果)且是清障/攻坚硬通货，机会成本高。
    # 故 YAN 的反制序列改为 BING 在前（_allow_bing 已按筹码分级开关，低筹码自然回落 XIAN）。
    _BEATS = {
        Card.YAN_DIE: (Card.BING_ZHENG, Card.XIAN_GONG),
        Card.QIANG_XING: (Card.YAN_DIE, Card.BING_ZHENG),
        Card.XIAN_GONG: (Card.QIANG_XING,),
        Card.BING_ZHENG: (Card.XIAN_GONG,),
    }
    _STAKES_RANK = {"GATE": 3, "PASS": 3, "TASK": 2, "OBSTACLE": 2, "DOCK": 1, "RESOURCE": 1}

    def _window_card(self, world, me):
        """反应式 3 拍出牌：读对手上一拍牌与当前胜点，按筹码分级反制；选最高筹码窗口。

        核心原则（Iter17 修正）：
        - 鲜度<80 时 XIAN 双方都不可用，BING 近无敌（唯一克星 XIAN 缺席）→ 此时 BING 是主牌，
          能克制则克制、不能克制则出 BING 求平，绝不弃权白送胜点（旧逻辑在此场景 0-2 空手输）。
        - 中筹码(TASK/OBSTACLE)解禁 BING（受 WINDOW_BING_RESERVE 约束，保留护卫点给潜在 GATE/PASS），
          避免任务窗口在鲜度<80 时结构性必输、丢 30 分任务分。
        - 第 2/3 拍：优先克制对手上一拍牌；无法克制则出同牌求平；再无法则出最强可用牌争取对手换牌时赢。
        - 胜负已定则弃权省成本。同帧多窗口只出 1 张（§5.4.2），选最高筹码者，其余弃权。
        """
        contests = self._my_active_contests(world)
        if not contests:
            return None
        # 交付告急：窗口出牌不阻断推进（独立动作类别），但耗好果/护卫点/马，保交付优先 → 弃权省成本。
        gm = self.ctx.game_map
        terminal = gm.terminal_nodes[0] if gm and gm.terminal_nodes else None
        if self._delivery_panicking(world, me, gm, me.current_node_id, terminal):
            return None
        c = contests[0]
        cid = c.get("contestId")
        if not cid:
            return None
        ri = c.get("roundIndex") or 1
        played = self._window_played.get(cid)
        if played and ri in played:
            return None  # 本拍已出过牌，不重复提交

        my_color = self._my_color(c)
        my_pt, opp_pt = self._points(c, my_color)
        stakes = self._stakes(c)
        allow_bing = self._allow_bing(me, stakes)
        allow_xian = stakes >= 2 and me.freshness >= 80 \
            and me.good_fruit >= config.XIAN_GONG_MIN_GOOD
        # 马匹预留：去路上还有需消耗马的活跃任务(T06,+30 分)且任务分未封顶 → 不把马用于
        # 窗口 QIANG（30 任务分 >> 一拍 QIANG 的胜面收益）；本帧马已被加速占用亦不再用于 QIANG。
        # 已有移动增益(buff)时 QIANG 免消耗，不受此约束。
        reserve_horse = (self._horse_planned_for_speed
                         or self._horse_requiring_task_ahead(world, me, gm,
                                                             me.current_node_id, terminal))
        avail = self._available_cards(me, allow_bing, allow_xian, reserve_horse)

        if my_pt >= 2 or opp_pt >= 2:
            card = Card.ABSTAIN  # 胜负已定，省成本
        else:
            opp_card = self._opp_last_card(world, c, my_color)
            roll = self._lead_roll(c, ri, world.round or 0) if config.WINDOW_MIXED_LEAD else 0.0
            card = self._choose_card(ri, opp_card, avail, roll)

        self._window_played.setdefault(cid, set()).add(ri)
        return actions.window_card(cid, card)

    def _choose_card(self, ri, opp_card, avail, roll=0.0):
        """单拍出牌选择：有对手上一拍信息时优先克制/求平/出最强；R1 领出按优先级或混合。"""
        if not avail:
            return Card.ABSTAIN  # 真负担不起任何牌
        if ri >= 2 and opp_card and opp_card != Card.ABSTAIN:
            counter = self._pick_counter(opp_card, avail)
            if counter is not None:
                return counter
            if opp_card in avail:
                return opp_card  # 无法克制则出同牌求平，避免白送胜点
            # 既无法克制也无法平：出最强可用牌争取对手换牌时赢，而非弃权（弃权对任何实牌都输）
            return self._strongest_available(avail)
        return self._lead_card(avail, roll)

    # 混合领出权重（反剥削）：偏好强牌，但在可用强牌间分散，避免恒定 BING 被针对
    _LEAD_WEIGHTS = {
        Card.BING_ZHENG: 0.50,
        Card.XIAN_GONG: 0.25,
        Card.QIANG_XING: 0.15,
        Card.YAN_DIE: 0.10,
    }

    def _lead_roll(self, c, ri, rnd):
        """确定性伪随机 roll ∈ [0,1)：由 contestId+roundIndex+round+playerId 哈希，可测可复现。"""
        key = "{}:{}:{}:{}".format(c.get("contestId"), ri, rnd, self.ctx.player_id)
        h = 0
        for ch in key:
            h = (h * 131 + ord(ch)) & 0xFFFFFFFF
        return (h % 1000) / 1000.0

    def _my_active_contests(self, world):
        """本方进行中窗口，按综合优先级降序；顺带清理已结束窗口的出牌记录与过期弃权标记。

        协议§5.4.2：每帧仅 1 个 contestId 出牌，其余按弃权。旧版纯按筹码排序会丢弃紧迫窗口
        （如 stakes2 但 deadline 已到 / 已到决胜拍），故改为综合优先级：筹码为主，叠加速胜
        关门价值、后拍紧迫性、deadline 临近度。

        Iter20：过滤命中 WINDOW_DRAW_RETRY_LIMIT 的弃权窗口（停在 DOCK 死磕 59 个窗口致 105 次
        重试的根因），并清理已结束/过期窗口的弃权标记。
        """
        contests = world.my_contests()
        if not contests:
            return []
        active_ids = {c.get("contestId") for c in contests}
        for cid in list(self._window_played):
            if cid not in active_ids:
                del self._window_played[cid]
        rnd = world.round or 0
        for cid in list(self._abstain_contests):
            if cid not in active_ids or self._abstain_contests[cid] <= rnd:
                del self._abstain_contests[cid]
        contests = [c for c in contests if not self._is_contest_abstained(world, c.get("contestId"))]
        return sorted(contests, key=lambda c: self._contest_priority(c, rnd, world), reverse=True)

    def _contest_priority(self, c, rnd, world):
        """窗口优先级：筹码×100（主导）+ 关门价值 + 后拍紧迫 + deadline 临近。"""
        stakes = self._stakes(c)
        ri = c.get("roundIndex") or 1
        my_color = self._my_color(c)
        my_pt, opp_pt = self._points(c, my_color)
        # 3 拍制下任一方达 1 胜点 → 再赢一拍即定胜负，关门价值高（优先响应避免被翻/锁定胜局）
        closeout = 6 if (my_pt >= 1 or opp_pt >= 1) else 0
        # 后拍更接近定胜负，紧迫性更高
        urgency = ri
        # deadline 临近：剩余响应帧≤1 时必须本帧出，强优先
        deadline = c.get("deadlineRound")
        deadline_bonus = 8 if (deadline and (deadline - rnd) <= 1) else 0
        return stakes * 100 + closeout + urgency + deadline_bonus

    def _stakes(self, c):
        return self._STAKES_RANK.get(c.get("contestType"), 1)

    def _my_color(self, c):
        return "RED" if c.get("redPlayerId") == self.ctx.player_id else "BLUE"

    def _points(self, c, my_color):
        if my_color == "RED":
            return (c.get("redPoint") or 0, c.get("bluePoint") or 0)
        return (c.get("bluePoint") or 0, c.get("redPoint") or 0)

    def _opp_last_card(self, world, c, my_color):
        """对手上一拍出的牌：优先 WINDOW_CARD_REVEAL 事件，回退到 contest.cards 映射。

        cards 映射的 key 协议未明确（颜色 "RED"/"BLUE" 或 playerId 字符串），两种都试以兼容服务端差异。
        """
        opp_color = "BLUE" if my_color == "RED" else "RED"
        cid = c.get("contestId")
        best_ri, best_card = -1, None
        for e in world.events:
            if e.get("type") != "WINDOW_CARD_REVEAL":
                continue
            p = e.get("payload") or {}
            if p.get("contestId") != cid:
                continue
            eri = p.get("roundIndex")
            if eri is not None and eri > best_ri:
                best_ri = eri
                best_card = p.get("redCard") if opp_color == "RED" else p.get("blueCard")
        if best_card:
            return best_card
        cards = c.get("cards") or {}
        card = cards.get(opp_color)
        if card is None:
            # fallback：服务端可能以 playerId 字符串作 key
            opp_pid = c.get("redPlayerId") if opp_color == "RED" else c.get("bluePlayerId")
            if opp_pid is not None:
                card = cards.get(str(opp_pid))
        return card

    def _available_cards(self, me, allow_bing, allow_xian, reserve_horse=False):
        """本帧可用且愿意出的牌集合（成本由调用方按筹码分级开关 BING/XIAN）。

        reserve_horse=True 时不在窗口消耗马（QIANG）：马留给前方需消耗马的 T06 任务
        （+30 任务分 >> 一拍 QIANG 胜面）或本帧已被加速占用。已有移动增益(buff)时
        QIANG 免消耗，不受此约束。
        """
        avail = []
        if allow_bing:
            avail.append(Card.BING_ZHENG)
        if allow_xian:
            avail.append(Card.XIAN_GONG)
        if me.resource_count(ResourceType.PASS_TOKEN) > 0 or me.resource_count(ResourceType.OFFICIAL_PERMIT) > 0:
            avail.append(Card.YAN_DIE)
        # QIANG_XING：已有马类/疾行令增益时免消耗（§5.4.3），否则耗 1 马
        if self._has_move_buff(me):
            avail.append(Card.QIANG_XING)
        elif not reserve_horse and (me.resource_count(ResourceType.FAST_HORSE) > 0
                                    or me.resource_count(ResourceType.SHORT_HORSE) > 0):
            avail.append(Card.QIANG_XING)
        return avail

    def _pick_counter(self, opp_card, avail):
        """从能克制对手牌的选项中，取成本最低且可用者。"""
        for card in self._BEATS.get(opp_card, ()):
            if card in avail:
                return card
        return None

    def _lead_card(self, avail, roll=0.0):
        """第 1 拍领出牌。

        - WINDOW_MIXED_LEAD 关（默认）：确定性优先级 BING>XIAN>QIANG>YAN（保单测稳定）。
        - WINDOW_MIXED_LEAD 开：按权重在可用强牌间混合（反剥削，避免恒领 BING 被反应式对手针对）。
          roll 由 contestId+roundIndex+round+playerId 哈希得，确定性可复现。

        鲜度<80 时 XIAN 双方都不可用，BING 仅输 XIAN → 近无敌，优先 BING；鲜度>=80 时 BING 仍是最稳强牌
        （仅输 XIAN，而 XIAN 成本高对手未必舍得）。无 BING 则 XIAN/QIANG/YAN。低筹码(RESOURCE/DOCK)
        因 _allow_bing 关闭 BING，自然回落到 QIANG(骑马免消耗)/YAN，与旧行为一致。
        """
        if not config.WINDOW_MIXED_LEAD or roll <= 0.0:
            for card in (Card.BING_ZHENG, Card.XIAN_GONG, Card.QIANG_XING, Card.YAN_DIE):
                if card in avail:
                    return card
            return Card.ABSTAIN
        # 混合：在可用强牌间按权重累积选择
        order = (Card.BING_ZHENG, Card.XIAN_GONG, Card.QIANG_XING, Card.YAN_DIE)
        weights = [self._LEAD_WEIGHTS.get(card, 0.0) for card in order]
        pairs = [(card, w) for card, w in zip(order, weights) if card in avail and w > 0]
        if not pairs:
            return Card.ABSTAIN
        tot = sum(w for _, w in pairs)
        r = roll * tot
        acc = 0.0
        for card, w in pairs:
            acc += w
            if r < acc:
                return card
        return pairs[-1][0]

    def _strongest_available(self, avail):
        """可用牌中最强者（按胜面排序 BING>XIAN>QIANG>YAN），全无则弃权。"""
        for card in (Card.BING_ZHENG, Card.XIAN_GONG, Card.QIANG_XING, Card.YAN_DIE):
            if card in avail:
                return card
        return Card.ABSTAIN

    def _allow_bing(self, me, stakes):
        """是否允许本拍出 BING（消耗 1 护卫点，4 点不恢复、唯一用途=BING）。

        - GATE/PASS(stakes3)：关键窗口（验核权/通行权关系交付），尽情花，guard>=1 即用。
        - TASK/OBSTACLE(stakes2)：任务分 30 > 1 护卫点，但保留 WINDOW_BING_RESERVE 给潜在 GATE/PASS。
        - RESOURCE/DOCK(stakes1)：guard 充足(g > WINDOW_BING_LOW_STAKES_RESERVE)时解禁——低筹码下红方不领
          过所/官凭、马只 1 匹，BING/XIAN 被关、YAN 无过所、QIANG 输 YAN/BING，旧逻辑只能 ABSTAIN 必输；
          BING 胜 YAN/QIANG、平 BING、仅负 XIAN，是低筹码下唯一能赢/平的牌。保留 2 点给中/高筹码窗口。
        """
        g = me.guard_action_point or 0
        if g <= 0:
            return False
        if stakes >= 3:
            return True
        if stakes == 2:
            return g > config.WINDOW_BING_RESERVE
        return g > config.WINDOW_BING_LOW_STAKES_RESERVE

    # ---- 辅助 ----

    # 主车队动作类型（协议附录 E/§4.1）：同帧最多 1 个，否则服务端判 INVALID_ACTION_CONFLICT。
    _MAIN_ACTION_TYPES = frozenset({
        Action.WAIT, Action.MOVE, Action.DELIVER, Action.VERIFY_GATE, Action.SET_GUARD,
        Action.BREAK_GUARD, Action.FORCED_PASS, Action.CLAIM_RESOURCE, Action.USE_RESOURCE,
        Action.CLAIM_TASK, Action.CLEAR, Action.PROCESS, Action.DOCK,
    })
    _RUSH_TACTIC_TYPES = frozenset({Action.RUSH_SPEED, Action.RUSH_PROTECT})

    def _dedup_actions(self, result):
        """协议§4.1 防御性去重：每类动作（主车队/小分队/急策/窗口）同帧≤1，超额丢弃保留首个。

        正常控制流不会产出同类重复（_keep_moving 已修为单主车队动作），此为兜底——
        防止任何路径回归产出 `[horse, MOVE]` 式非法并发导致 0705 真机 201 次冲突循环。
        """
        seen_main = seen_squad = seen_rush = seen_window = False
        out = []
        for a in result:
            act = a.get("action", "")
            if act in self._MAIN_ACTION_TYPES:
                if seen_main:
                    continue
                seen_main = True
            elif act.startswith("SQUAD_"):
                if seen_squad:
                    continue
                seen_squad = True
            elif act in self._RUSH_TACTIC_TYPES:
                if seen_rush:
                    continue
                seen_rush = True
            elif act == Action.WINDOW_CARD:
                if seen_window:
                    continue
                seen_window = True
            out.append(a)
        return out

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

    def _can_afford(self, world, gm, node, extra_frames, terminal, safety_margin=None):
        """做完 extra_frames 读条后仍能按时交付（含未验核时的验核耗时）。

        safety_margin 默认用通用 DELIVER_TIME_SAFETY_MARGIN(25)；任务绕路等高收益场景可传更紧的
        TASK_DETOUR_SAFETY_MARGIN(15) 以释放预算（单任务 +30 分 > ~3 帧用时分的潜在损失）。
        """
        if terminal is None:
            return True
        est = self._deliver_estimate(world, world.me, gm, node, terminal)
        if est == _INF:
            return False
        margin = safety_margin if safety_margin is not None else config.DELIVER_TIME_SAFETY_MARGIN
        end = (world.round or 0) + extra_frames + est + margin
        return end <= (self.ctx.duration_round or 600)

    # ---- 固定处理完成跟踪 ----

    def _update_process_memory(self, world, me, node):
        if node != self._stay_node:
            self._stay_node = node
            self._processed_here = False
            self._offensive_guard_node = None  # 已离开上一种卡节点，允许在新节点种卡
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
