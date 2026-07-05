"""本地假服务端（开发工具，非提交物）——全流程仿真（M5 版）。

加载 samples/map_config.json 构建 start；模拟移动/处理/验核/交付 + M4 收益(资源/任务/急策) +
M5 对抗联调：道路障碍与主车队清障(CLEAR)、小分队探路(SQUAD_SCOUT)与宫门验核减时。

为验证突破逻辑，默认在 S13（终段唯一通路，不可绕行）放置一个道路障碍，迫使客户端 CLEAR。

简化口径（仅联调）：MOVE 按真实 §2.3.2 移动量结算（ceil(距离×耗时系数)，每帧推进 floor(基础×1000÷天气倍率)）；
各读条占其帧数；CLEAR 占 6 帧且耗 1 好果；到 S14 触发 RUSH（且第 450 帧强制触发，§6.5）；
小分队探路 3 帧后在目标落下己方标记；验核时若宫门有己方标记则读条 -3（最低3）并消耗标记；
鲜度按路线类型(0.045~0.07)×天气系数×急策系数结算（§3.2.2），跨 90/80/.../10 阈值触发好果转坏（§3.2.1）；
4 次天气事件按 §2.5 窗口确定性排期（HOT/HEAVY_RAIN/MOUNTAIN_FOG/HOT）；马/疾行仅登记 buff。

用法：python scripts/mock_server.py [host] [port] [maxRounds]（默认 127.0.0.1:8081, 600 帧）。
"""

import json
import math
import os
import socket
import sys

W = 5

# 路线耗时系数（§2.3.2）——与 core/rules.py ROUTE_TIME_COEF 对齐
ROUTE_TIME_COEF = {"ROAD": 1380, "WATER": 1250, "MOUNTAIN": 1780, "BRANCH": 1550}
# 每帧基础移动量（§2.3.2）
BASE_MOVE = {"NONE": 1000, "FAST_HORSE": 1200, "SHORT_HORSE": 1150, "RUSH_SPEED": 1300}
# 每帧移动鲜度损耗（§3.2.2）
FRESHNESS_LOSS_MOVE = {"ROAD": 0.055, "WATER": 0.045, "MOUNTAIN": 0.07, "BRANCH": 0.065}
FRESHNESS_LOSS_IDLE = 0.05
# 鲜度首次低于这些阈值时各触发 1 篓好果转坏（§3.2.1）
GOOD_TO_BAD_THRESHOLDS = (90, 80, 70, 60, 50, 40, 30, 20, 10)
# 天气排期（确定性，对齐 §2.5 四次事件窗口 80-120/200-240/320-360/440-480，各持续 60 帧）
WEATHER_SCHEDULE = [("HOT", 100, 160), ("HEAVY_RAIN", 220, 280),
                    ("MOUNTAIN_FOG", 340, 400), ("HOT", 460, 520)]
WEATHER_MOVE_MULT = {("HEAVY_RAIN", "WATER"): 1350, ("MOUNTAIN_FOG", "MOUNTAIN"): 1100}
WEATHER_FRESH_COEF = {"HOT": 1.5, "HEAVY_RAIN": 1.3, "MOUNTAIN_FOG": 1.0}
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAP = os.path.join(_ROOT, "samples", "map_config.json")

OBSTACLES = {"S13"}  # 终段唯一通路上的障碍：不可绕行 → 迫使客户端突破(CLEAR)
TASKS = [
    {"taskId": "TK1", "taskTemplateId": "T01", "name": "限时过关", "nodeId": "S09", "score": 30, "processRound": 3},
    {"taskId": "TK2", "taskTemplateId": "T02", "name": "抵驿催运", "nodeId": "S11", "score": 30, "processRound": 4},
    {"taskId": "TK3", "taskTemplateId": "T01", "name": "限时过关", "nodeId": "S13", "score": 30, "processRound": 3},
    # Iter16 验证：T06(消耗马)+T04(清障) 不再被跳过，5 模板可达任务分 180
    {"taskId": "TK4", "taskTemplateId": "T06", "name": "争马换乘", "nodeId": "S11", "score": 30, "processRound": 3},
    {"taskId": "TK5", "taskTemplateId": "T04", "name": "清障任务", "nodeId": "S13", "score": 30, "processRound": 6,
     "processType": "CLEAR_OBSTACLE"},
]

# ---- 窗口争夺仿真（Iter18 补全 / Iter19 加 RESOURCE 触发）----
# mock 原仅 `"contests": []`，窗口出牌策略从未端到端验证。现补全 3 拍窗口争夺：
# 触发点 = (nodeId, action, target)；红方在该节点对 target 提交 contestable 动作时创建窗口。
# Iter19 起 `_allow_bing` 在低筹码 guard 充足时解禁 BING，红方在 RESOURCE 窗口也能出牌，故加 RESOURCE 触发。
WINDOW_ENABLED = os.environ.get("MOCK_WINDOW", "1") != "0"
WINDOW_TRIGGERS = {
    ("S03", "CLAIM_RESOURCE", "ICE_BOX"),  # RESOURCE 窗口（低筹码 stakes1）：验 Iter19 BING 解禁
    ("S11", "CLAIM_TASK", "TK2"),          # TASK 窗口（中筹码 stakes2）：验领出/反制/成本
}
WINDOW_NODES = {n for (n, _, _) in WINDOW_TRIGGERS}

# 牌克制表（与 client strategy/decision.py _BEATS 一致，Iter18）：BEATS[被克牌] = 克制它的牌
BEATS = {
    "YAN_DIE": ("BING_ZHENG", "XIAN_GONG"),
    "QIANG_XING": ("YAN_DIE", "BING_ZHENG"),
    "XIAN_GONG": ("QIANG_XING",),
    "BING_ZHENG": ("XIAN_GONG",),
}
STAKES_RANK = {"GATE": 3, "PASS": 3, "TASK": 2, "OBSTACLE": 2, "DOCK": 1, "RESOURCE": 1}
CARD_COST = {  # 牌 → 资源代价类型（用于蓝方扣减；红方由各字段直接扣）
    "BING_ZHENG": "guard", "XIAN_GONG": "good", "QIANG_XING": "horse",
    "YAN_DIE": "permit", "ABSTAIN": None,
}

# ---- 拒绝码仿真（Iter20）----
# 0705 真机 37/37 REJECT_LOOP 根因是客户端重发被拒动作，旧 mock 恒 accept 无法回归 P0 拒绝反馈链路。
# 默认恒 accept（保 Iter14~Iter19 基线）；通过环境变量注入拒绝以端到端验证客户端拉黑/退避/弃权后断环：
#   MOCK_REJECT_TASK=<taskId>            对该 taskId 的 CLAIM_TASK 恒拒 TASK_REQUIREMENT_NOT_MET
#   MOCK_REJECT_RESOURCE=<nodeId>:<type> 对该节点资源的 CLAIM_RESOURCE 恒拒 OBJECT_BUSY
# INVALID_ACTION_CONFLICT（>1 主车队动作，§4.1）为常开回归守卫——P1 修复后客户端不应再触发。
REJECT_TASK = os.environ.get("MOCK_REJECT_TASK", "").strip()
REJECT_RESOURCE = os.environ.get("MOCK_REJECT_RESOURCE", "").strip()


def encode(envelope):
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return str(len(body)).zfill(W).encode("ascii") + body


def recv_one(sock, buf):
    while True:
        if len(buf) >= W and buf[:W].isdigit():
            total = W + int(buf[:W])
            if len(buf) >= total:
                body = bytes(buf[W:total])
                del buf[:total]
                return json.loads(body.decode("utf-8")), buf
        chunk = sock.recv(65536)
        if not chunk:
            return None, buf
        buf.extend(chunk)


def load_map():
    with open(_MAP, encoding="utf-8") as fh:
        return json.load(fh)


def build_edges(edges):
    """返回 (adj, meta)：adj 为可通行邻居表；meta[(a,b)] = (distance, routeType, coef)。

    mock 按双向可通行处理（方向是次要保真项）；真实移动量按 §2.3.2 计算。
    """
    adj, meta = {}, {}
    for e in edges:
        a, b = e["fromNodeId"], e["toNodeId"]
        d, t = e["distance"], e["routeType"]
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
        coef = ROUTE_TIME_COEF.get(t, 1550)
        meta[(a, b)] = meta[(b, a)] = (d, t, coef)
    return adj, meta


def active_weather(rnd):
    for t, s, e in WEATHER_SCHEDULE:
        if s <= rnd < e:
            return t
    return None


def build_start(mc, match_id, red_id, blue_id):
    return {"msg_name": "start", "msg_data": {
        "matchId": match_id, "rulesVersion": "mock", "round": 1, "tick": 0, "durationRound": 600,
        "map": {"maxX": mc["map"]["maxX"], "maxY": mc["map"]["maxY"],
                "gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14",
                                       "terminalNodeIds": ["S15"], "safeZoneNodeIds": ["S15"]}}},
        "players": [{"playerId": red_id, "camp": 0, "teamId": "RED", "name": "mock-red"},
                    {"playerId": blue_id, "camp": 1, "teamId": "BLUE", "name": "mock-blue"}],
        "nodes": mc["nodes"], "edges": mc["edges"], "processNodes": mc["processNodes"],
        "resources": [{"nodeId": r["nodeId"], "resourceType": r["resourceType"], "count": 1, "claimRound": 2}
                      for r in mc.get("visibleResources", [])],
        "taskTemplates": [
            {"taskTemplateId": "T01", "score": 30, "processRound": 3},
            {"taskTemplateId": "T02", "score": 30, "processRound": 4},
            {"taskTemplateId": "T04", "score": 30, "processRound": 6, "processType": "CLEAR_OBSTACLE"},
            {"taskTemplateId": "T06", "score": 30, "processRound": 3,
             "requiredResourceTypes": ["FAST_HORSE", "SHORT_HORSE"]},
        ]}}


class Sim:
    HORSE_DUR = {"FAST_HORSE": 20, "SHORT_HORSE": 14}
    SCOUT_DELAY = 3

    def __init__(self, mc, me_id):
        self.me_id = me_id
        self.adj, self.edge_meta = build_edges(mc["edges"])
        self.proc_round = {p["nodeId"]: p["processRound"] for p in mc["processNodes"]}
        self.gate, self.terminal = "S14", "S15"
        self.verify_round = self.proc_round.get("S14", 6)
        self.stock = {}
        for r in mc.get("visibleResources", []):
            self.stock.setdefault(r["nodeId"], {}).setdefault(r["resourceType"], 0)
            self.stock[r["nodeId"]][r["resourceType"]] += 1
        self.tasks = [dict(t, completed=False) for t in TASKS]
        self.obstacles = set(OBSTACLES)
        self.node_type = {n["nodeId"]: n.get("type") for n in mc["nodes"]}
        self.guards = {}         # node -> {ownerTeamId, defense, active, maxDefense}（己方设卡）
        self.marks = {}          # node -> set(teamId)
        self.pending_scouts = []  # [arrive_round, node, team]
        self.pending_clears = []  # [arrive_round, node]（小分队清障延迟落地）
        self.pos, self.state, self.target = "S01", "IDLE", None
        self.reading, self.read_kind, self.read_ctx, self.timer = False, None, None, 0
        # 真实移动累计（§2.3.2）：move_amount=到站所需移动量，move_progress=已推进量
        self.move_amount, self.move_progress, self.move_route = 0, 0, None
        self.verified = self.delivered = False
        self.good, self.bad, self.fresh, self.rush = 100, 0, 100.0, False
        self.triggered_thresholds = set()  # 已触发的好果转坏阈值（§3.2.1）
        self.inv, self.buffs, self.rush_used, self.task_score = {}, [], 0, 0
        self.squad_available = 8
        self._weather_now = None
        # 窗口争夺状态
        self.guard_ap = 4            # 红方护卫行动点（BING 消耗，4 点不恢复）
        self.contests = {}           # contestId -> 窗口状态 dict
        self.contest_seq = 0
        self.contest_by_object = {}  # (ctype,node,target) -> contestId（活跃窗口去重）
        # 蓝方虚拟资源池（蓝方为静态 dummy，仅参与窗口出牌；不移动不衰减）
        self.blue = {"guard": 4, "good": 50, "fresh": 100.0, "horse": 4, "permit": 4}
        self.last_action_results = []  # 上一帧动作结果（供下一帧 actionResults，Iter20 拒绝码仿真）

    # ---- 快照 ----
    def snapshot(self):
        return {"playerId": self.me_id, "teamId": "RED", "state": self.state,
                "currentNodeId": self.pos, "nextNodeId": self.target,
                "freshness": round(self.fresh, 3), "goodFruit": self.good, "badFruit": self.bad, "frozenGoodFruit": 0,
                "squadAvailable": self.squad_available, "guardActionPoint": self.guard_ap,
                "verified": self.verified, "delivered": self.delivered, "retired": False,
                "resources": {k: v for k, v in self.inv.items() if v > 0},
                "buffs": [{"type": b["type"], "remainingRound": b["remainingRound"]} for b in self.buffs],
                "rushTacticUsedCount": self.rush_used, "taskScore": self.task_score,
                "bountyScore": 0, "totalScore": 0}

    def tasks_view(self):
        return [{"taskId": t["taskId"], "taskTemplateId": t["taskTemplateId"], "name": t.get("name"),
                 "nodeId": t["nodeId"], "score": t["score"], "processRound": t["processRound"],
                 "active": not t["completed"], "completed": t["completed"], "failed": False}
                for t in self.tasks]

    def nodes_view(self, node_ids):
        out = []
        for nid in node_ids:
            scouted = [{"teamId": t, "remainRound": 45, "processReduceRound": 3, "remainingTriggers": 1}
                       for t in self.marks.get(nid, ())]
            g = self.guards.get(nid)
            guard = ({"ownerTeamId": g["ownerTeamId"], "defense": g["defense"],
                      "active": g["active"], "maxDefense": g["maxDefense"]} if g else None)
            out.append({"nodeId": nid, "resourceStock": dict(self.stock.get(nid, {})),
                        "hasObstacle": nid in self.obstacles, "obstacleType": "ROCKFALL" if nid in self.obstacles else None,
                        "guard": guard, "scouted": scouted, "canWindow": nid in WINDOW_NODES})
        return out

    def _guard_cap(self, nid):
        t = self.node_type.get(nid)
        if t == "KEY_PASS":
            return 7
        if nid == self.gate:
            return 4
        return 6

    # ---- 推进 ----
    def resolve(self, actions, rnd):
        events = []
        self._weather_now = active_weather(rnd)
        # §6.5 RUSH 强制触发：第 450 帧对局未结束必定触发
        if not self.rush and rnd >= 450:
            self.rush = True
            events.append(self._ev("RUSH_START", rnd))
        # 区分主车队动作 / 小分队 / 窗口出牌（不同动作类别不互占额度，§4.1）。
        # Iter20：先做协议合规校验，被拒动作不执行并记录结果供下一帧 actionResults。
        rejections = self._validate_actions(actions)
        main = squad = card = None
        for i, a in enumerate(actions):
            if i in rejections:
                continue
            act = a.get("action", "")
            if act.startswith("SQUAD_"):
                if squad is None:
                    squad = a
            elif act == "WINDOW_CARD":
                if card is None:
                    card = a
            else:
                if main is None:
                    main = a
        self.last_action_results = []
        for i, a in enumerate(actions):
            if i in rejections:
                self.last_action_results.append(
                    {"action": a.get("action", "WAIT"), "accepted": False,
                     "result": "REJECTED", "errorCode": rejections[i]})
            else:
                self.last_action_results.append(
                    {"action": a.get("action", "WAIT"), "accepted": True, "result": "ACCEPTED"})
        act = main.get("action") if main else None

        # 1) 窗口出牌：记录本拍红方牌（随后在 _resolve_contests 与蓝方一同结算）
        if card:
            self._process_window_card(card, rnd)

        if not self.reading and self.state in ("MOVING", "WAITING"):
            # 真实服务端行为：路线边上只有"主动续行"(MOVE 到当前目标 / 马类)才前进；
            # 否则(空动作等)停为 WAITING(暴露空等卡死)。旧客户端发 [] 会在此卡死。
            if act == "USE_RESOURCE":
                events += self._use(main, rnd)
                self.state = "MOVING"
                self._tick_move(rnd, events)
            elif act == "MOVE" and main.get("targetNodeId") == self.target:
                self.state = "MOVING"
                self._tick_move(rnd, events)
            else:
                self.state = "WAITING"
        elif self.reading:
            self.timer -= 1
            if self.timer <= 0:
                events += self._finish_read(rnd)
        elif self.state in ("IDLE", "COST_BANKRUPT"):
            # 优先：contestable 动作在触发节点 → 创建窗口争夺（本帧不执行底层动作，等结算）
            cev = self._maybe_create_contest(main, rnd) if (WINDOW_ENABLED and act) else []
            if cev:
                events += cev
            else:
                events += self._apply_idle(act, main, rnd)

        # 2) 窗口拍结算：红方已出牌的活跃窗口推进一拍 / 收尾
        events += self._resolve_contests(rnd)

        if squad:
            events += self._apply_squad(squad, rnd)
        events += self._deliver_scouts(rnd)
        events += self._deliver_clears(rnd)

        self._tick_buffs()
        # 鲜度按路线类型 + 天气系数 + 急策系数（§3.2.2）
        base_loss = FRESHNESS_LOSS_MOVE.get(self.move_route, FRESHNESS_LOSS_IDLE) \
            if self.state == "MOVING" and self.move_route else FRESHNESS_LOSS_IDLE
        fcoef = WEATHER_FRESH_COEF.get(self._weather_now, 1.0)
        if self._has_buff("RUSH_SPEED"):
            fcoef *= 1.25
        if self._has_buff("RUSH_PROTECT"):
            fcoef *= 0.2
        before = self.fresh
        self.fresh = max(0.0, self.fresh - base_loss * fcoef)
        # 好果转坏阈值（§3.2.1）：首次低于 90/80/.../10 各转 1 篓好果为坏果
        for t in GOOD_TO_BAD_THRESHOLDS:
            if before >= t > self.fresh and t not in self.triggered_thresholds:
                self.triggered_thresholds.add(t)
                if self.good > 0:
                    self.good -= 1
                    self.bad += 1
        return events

    def _validate_actions(self, actions):
        """协议合规校验：返回 {action_idx: errorCode}，被拒动作不执行（Iter20 拒绝码仿真）。

        - INVALID_ACTION_CONFLICT（常开）：>1 主车队动作（§4.1 每帧≤1），拒第 2+ 个。回归守卫——
          P1 修复后客户端不应再触发；若回归产出 [horse, MOVE] 式并发，mock 拒其一副使客户端察觉。
        - TASK_REQUIREMENT_NOT_MET（MOCK_REJECT_TASK=<taskId>）：对该 taskId 的 CLAIM_TASK 恒拒——
          验客户端拉黑 taskId 后不再重发（0705 旧版会重发 142 次致未交付）。
        - OBJECT_BUSY（MOCK_REJECT_RESOURCE=<nodeId>:<type>）：对该节点资源的 CLAIM_RESOURCE 恒拒——
          验节点忙冷却后不再当帧重发。
        """
        rejections = {}
        main_count = 0
        for i, a in enumerate(actions):
            act = a.get("action", "")
            if act.startswith("SQUAD_") or act == "WINDOW_CARD":
                continue  # 独立动作类别（§4.1），不占主车队额度
            main_count += 1
            if main_count > 1:
                rejections[i] = "INVALID_ACTION_CONFLICT"
                continue
            if act == "CLAIM_TASK" and REJECT_TASK and a.get("taskId") == REJECT_TASK:
                rejections[i] = "TASK_REQUIREMENT_NOT_MET"
            elif act == "CLAIM_RESOURCE" and REJECT_RESOURCE:
                try:
                    rn, rt = REJECT_RESOURCE.split(":", 1)
                except ValueError:
                    rn, rt = "", ""
                if a.get("targetNodeId") == rn and a.get("resourceType") == rt:
                    rejections[i] = "OBJECT_BUSY"
        return rejections

    def _apply_idle(self, act, main, rnd):
        events = []
        if act == "MOVE":
            tgt = main.get("targetNodeId")
            if tgt in self.adj.get(self.pos, ()) and tgt not in self.obstacles:
                d, t, coef = self.edge_meta[(self.pos, tgt)]
                self.move_amount = math.ceil(d * coef)   # 到站所需移动量（§2.3.2）
                self.move_progress = 0
                self.move_route = t
                self.state, self.target = "MOVING", tgt
        elif act == "PROCESS":
            if self.pos in self.proc_round:
                pr = self.proc_round[self.pos]
                if "RED" in self.marks.get(self.pos, set()):  # 探路标记减处理帧
                    pr = max(2, pr - 3)
                    self.marks[self.pos].discard("RED")
                    events.append(self._ev("SCOUT_MARKER_CONSUME", rnd, nodeId=self.pos))
                self._start_read("PROCESS", pr, None, "PROCESSING")
        elif act == "VERIFY_GATE":
            if self.rush and self.pos == self.gate and not self.verified:
                vr = self.verify_round
                if "RED" in self.marks.get(self.gate, set()):
                    vr = max(3, vr - 3)
                    self.marks[self.gate].discard("RED")
                    events.append(self._ev("SCOUT_MARKER_CONSUME", rnd, nodeId=self.gate))
                self._start_read("VERIFY", vr, None, "VERIFYING")
        elif act == "CLEAR":
            tgt = main.get("targetNodeId")
            if tgt in self.obstacles and (tgt == self.pos or tgt in self.adj.get(self.pos, ())) and self.good > 1:
                self._start_read("CLEAR", 6, tgt, "PROCESSING")
        elif act == "CLAIM_RESOURCE":
            res, node = main.get("resourceType"), main.get("targetNodeId") or self.pos
            obj_key = ("RESOURCE", node, res)
            if obj_key in self.contest_by_object:
                pass  # 该资源正处窗口争夺中，底层领取由窗口结算后授予（防重复创建/重复读条）
            elif node == self.pos and self.stock.get(self.pos, {}).get(res, 0) > 0:
                self._start_read("CLAIM", 2, res, "PROCESSING")
        elif act == "CLAIM_TASK":
            t = self._find_task(main.get("taskId"))
            if t and not t["completed"]:
                tid = main.get("taskId")
                obj_key = ("TASK", self.pos, tid)
                if obj_key in self.contest_by_object:
                    pass  # 该任务正处窗口争夺中，由窗口结算后授予
                else:
                    # T04 清障任务：可在障碍节点或相邻节点处理（§5.2）；其他任务必须在任务节点
                    if t.get("processType") == "CLEAR_OBSTACLE":
                        ok = t["nodeId"] == self.pos or t["nodeId"] in self.adj.get(self.pos, ())
                    else:
                        ok = t["nodeId"] == self.pos
                    if ok:
                        self._start_read("TASK", t["processRound"], t["taskId"], "PROCESSING")
        elif act == "USE_RESOURCE":
            events += self._use(main, rnd)
        elif act == "RUSH_PROTECT":
            if self.rush and self.rush_used == 0:
                self.buffs.append({"type": "RUSH_PROTECT", "remainingRound": 30})
                self.rush_used += 1
                events.append(self._ev("RUSH_TACTIC_USE", rnd, tactic="RUSH_PROTECT"))
        elif act == "RUSH_SPEED":
            if self.rush and self.rush_used == 0 and not self._has_move_buff():
                self.buffs.append({"type": "RUSH_SPEED", "remainingRound": 15})
                self.rush_used += 1
                events.append(self._ev("RUSH_TACTIC_USE", rnd, tactic="RUSH_SPEED"))
        elif act == "DELIVER":
            if self.pos == self.terminal and self.verified and self.good > 0 and self.fresh > 0:
                self.delivered = True
                events.append(self._ev("DELIVER_SUCCESS", rnd))
        elif act == "SET_GUARD":
            tgt = main.get("targetNodeId") or self.pos
            extra = main.get("extraGoodFruit", 0) or 0
            if (tgt == self.pos and tgt != self.terminal and not self.guards.get(tgt)
                    and len(self.guards) < 2 and self.good >= extra):
                self._start_read("SET_GUARD", 4, (tgt, extra), "PROCESSING")
        return events

    def _apply_squad(self, squad, rnd):
        a, tgt = squad.get("action"), squad.get("targetNodeId")
        if a == "SQUAD_SCOUT" and self.squad_available > 0 and tgt:
            self.squad_available -= 1
            self.pending_scouts.append([rnd + self.SCOUT_DELAY, tgt, "RED"])
            return [self._ev("SQUAD_DISPATCH", rnd, targetNodeId=tgt, action="SQUAD_SCOUT")]
        if a == "SQUAD_CLEAR" and self.squad_available >= 2 and tgt in self.obstacles:
            self.squad_available -= 2
            self.pending_clears.append([rnd + self.SCOUT_DELAY, tgt])
            return [self._ev("SQUAD_DISPATCH", rnd, targetNodeId=tgt, action="SQUAD_CLEAR")]
        if a == "SQUAD_REINFORCE" and self.squad_available >= 2 and tgt and tgt in self.guards:
            self.squad_available -= 2
            g = self.guards[tgt]
            g["defense"] = min(g["maxDefense"], g["defense"] + 2)
            return [self._ev("SQUAD_DISPATCH", rnd, targetNodeId=tgt, action=a,
                             defense=g["defense"])]
        if a == "SQUAD_WEAKEN" and self.squad_available >= 2 and tgt:
            self.squad_available -= 2  # 本 mock 无敌方设卡，仅记消耗
            return [self._ev("SQUAD_DISPATCH", rnd, targetNodeId=tgt, action=a)]
        return []

    def _deliver_scouts(self, rnd):
        ev, still = [], []
        for arr, node, team in self.pending_scouts:
            if arr <= rnd:
                self.marks.setdefault(node, set()).add(team)
                ev.append(self._ev("SCOUT_MARKER_ADD", rnd, nodeId=node, teamId=team))
            else:
                still.append([arr, node, team])
        self.pending_scouts = still
        return ev

    def _deliver_clears(self, rnd):
        ev, still = [], []
        for arr, node in self.pending_clears:
            if arr <= rnd:
                self.obstacles.discard(node)
                ev.append(self._ev("OBSTACLE_CLEAR", rnd, nodeId=node, byTeam="RED"))
            else:
                still.append([arr, node])
        self.pending_clears = still
        return ev

    def _tick_move(self, rnd, events):
        # 每帧移动量 = floor(基础每帧移动量 × 1000 ÷ 天气通行倍率)（§2.3.2）
        base = (1300 if self._has_buff("RUSH_SPEED")
                else 1200 if self._has_buff("FAST_HORSE")
                else 1150 if self._has_buff("SHORT_HORSE")
                else 1000)
        wmult = WEATHER_MOVE_MULT.get((self._weather_now, self.move_route), 1000)
        per = (base * 1000) // wmult
        self.move_progress += per
        if self.move_progress >= self.move_amount:
            self.pos, self.target, self.state = self.target, None, "IDLE"
            self.move_route = None
            events.append(self._ev("NODE_ENTER", rnd, nodeId=self.pos))
            if self.pos == self.gate and not self.rush:
                self.rush = True
                events.append(self._ev("RUSH_START", rnd))

    def _start_read(self, kind, frames, ctx, state_str):
        self.reading, self.read_kind, self.read_ctx = True, kind, ctx
        self.timer, self.state = frames, state_str

    def _finish_read(self, rnd):
        self.reading, self.state = False, "IDLE"
        kind, ctx = self.read_kind, self.read_ctx
        if kind == "PROCESS":
            return [self._ev("PROCESS_COMPLETE", rnd, nodeId=self.pos)]
        if kind == "VERIFY":
            self.verified = True
            return [self._ev("VERIFY_GATE_COMPLETE", rnd)]
        if kind == "CLEAR":
            self.obstacles.discard(ctx)
            self.good -= 1
            return [self._ev("OBSTACLE_CLEAR", rnd, nodeId=ctx)]
        if kind == "CLAIM":
            self.stock[self.pos][ctx] -= 1
            self.inv[ctx] = self.inv.get(ctx, 0) + 1
            return [self._ev("RESOURCE_CLAIM", rnd, nodeId=self.pos, resourceType=ctx)]
        if kind == "TASK":
            t = self._find_task(ctx)
            t["completed"] = True
            self.task_score += t["score"]
            evs = [self._ev("TASK_COMPLETE", rnd, taskId=ctx, score=t["score"], taskScore=self.task_score)]
            # T04 清障任务完成同步清障（§5.2）
            if t.get("processType") == "CLEAR_OBSTACLE" and t["nodeId"] in self.obstacles:
                self.obstacles.discard(t["nodeId"])
                evs.append(self._ev("OBSTACLE_CLEAR", rnd, nodeId=t["nodeId"]))
            return evs
        if kind == "SET_GUARD":
            node, extra = ctx
            self.good -= extra
            cap = self._guard_cap(node)
            defense = min(cap, 2 + extra * 2)
            self.guards[node] = {"ownerTeamId": "RED", "defense": defense,
                                 "active": True, "maxDefense": cap}
            return [self._ev("GUARD_SET", rnd, nodeId=node, defense=defense)]
        return []

    # ---- 窗口争夺仿真（Iter18）----

    def contests_view(self, red_id, blue_id):
        """下发活跃窗口列表（协议 §inquire.contests[]）。cards 用颜色 key（客户端 _opp_last_card 主路径）。"""
        out = []
        for c in self.contests.values():
            entry = {
                "contestId": c["contestId"], "contestType": c["contestType"],
                "targetNodeId": c["node"],
                "redPlayerId": red_id, "bluePlayerId": blue_id,
                "roundIndex": c["roundIndex"], "totalRounds": 3,
                "redPoint": c["redPoint"], "bluePoint": c["bluePoint"],
                "deadlineRound": c["deadlineRound"], "resolved": False,
                "sourceActionTypes": {str(red_id): c["source_action"], str(blue_id): c["source_action"]},
            }
            if c["contestType"] == "RESOURCE":
                entry["resourceType"] = c["target"]
            elif c["contestType"] == "TASK":
                entry["taskId"] = c["target"]
            # cards：上一拍已揭示的双方牌（供客户端反应式出牌读取；首拍空）
            if c["last_red"] or c["last_blue"]:
                entry["cards"] = {"RED": c["last_red"], "BLUE": c["last_blue"]}
            else:
                entry["cards"] = {}
            out.append(entry)
        return out

    def _maybe_create_contest(self, main, rnd):
        """contestable 动作在触发节点且对象可用、无活跃窗口时创建窗口。返回事件列表（空=未创建）。"""
        act = main.get("action")
        if act == "CLAIM_RESOURCE":
            res = main.get("resourceType")
            if (self.pos, "CLAIM_RESOURCE", res) not in WINDOW_TRIGGERS:
                return []
            if self.stock.get(self.pos, {}).get(res, 0) <= 0:
                return []
            ctype, target = "RESOURCE", res
        elif act == "CLAIM_TASK":
            tid = main.get("taskId")
            if (self.pos, "CLAIM_TASK", tid) not in WINDOW_TRIGGERS:
                return []
            t = self._find_task(tid)
            if not t or t["completed"]:
                return []
            ctype, target = "TASK", tid
        else:
            return []
        obj_key = (ctype, self.pos, target)
        if obj_key in self.contest_by_object:
            return []  # 已有活跃窗口，不重复创建
        self.contest_seq += 1
        cid = "C_%03d_%03d" % (rnd, self.contest_seq)
        self.contests[cid] = {
            "contestId": cid, "contestType": ctype, "node": self.pos, "target": target,
            "object_key": obj_key, "roundIndex": 1, "redPoint": 0, "bluePoint": 0,
            "red_card": None, "blue_card": None, "last_red": None, "last_blue": None,
            "deadlineRound": rnd + 2, "source_action": act,
        }
        self.contest_by_object[obj_key] = cid
        return [self._ev("WINDOW_CONTEST_START", rnd, contestId=cid, contestType=ctype,
                         targetNodeId=self.pos, resourceType=target if ctype == "RESOURCE" else None,
                         taskId=target if ctype == "TASK" else None)]

    def _process_window_card(self, card_action, rnd):
        """记录红方本拍出的牌（等待与蓝方一同结算）。"""
        cid = card_action.get("contestId")
        c = self.contests.get(cid)
        if not c or c["red_card"] is not None:
            return  # 未知窗口或本拍已出，忽略
        c["red_card"] = card_action.get("card") or "ABSTAIN"

    def _resolve_contests(self, rnd):
        """对红方已出牌的活跃窗口：蓝方出牌 → 结算本拍 → 推进 roundIndex；满 3 拍收尾。"""
        evs = []
        for cid in list(self.contests.keys()):
            c = self.contests[cid]
            if c["red_card"] is None:
                continue  # 红方本拍未出牌，等待
            ri = c["roundIndex"]
            blue_card = self._blue_choose(c, ri)
            red_card = c["red_card"]
            self._deduct_red_card(red_card)
            self._deduct_blue_card(blue_card)
            winner = self._resolve_beat(red_card, blue_card)
            if winner == "RED":
                c["redPoint"] += 1
            elif winner == "BLUE":
                c["bluePoint"] += 1
            c["last_red"], c["last_blue"] = red_card, blue_card
            evs.append(self._ev("WINDOW_CARD_REVEAL", rnd, contestId=cid, roundIndex=ri,
                                redCard=red_card, blueCard=blue_card, winner=winner or "DRAW",
                                redPoint=c["redPoint"], bluePoint=c["bluePoint"]))
            c["red_card"] = c["blue_card"] = None
            c["roundIndex"] += 1
            c["deadlineRound"] = rnd + 2
            if c["roundIndex"] > 3:
                evs += self._finalize_contest(c, rnd)
                del self.contests[cid]
        return evs

    def _resolve_beat(self, red_card, blue_card):
        if red_card == "ABSTAIN" and blue_card == "ABSTAIN":
            return None
        if red_card == "ABSTAIN":
            return "BLUE"
        if blue_card == "ABSTAIN":
            return "RED"
        if red_card == blue_card:
            return None
        if red_card in BEATS.get(blue_card, ()):
            return "RED"
        if blue_card in BEATS.get(red_card, ()):
            return "BLUE"
        return None

    def _finalize_contest(self, c, rnd):
        cid, ctype, node, target = c["contestId"], c["contestType"], c["node"], c["target"]
        red_won = c["redPoint"] > c["bluePoint"]
        draw = c["redPoint"] == c["bluePoint"]
        winner_team = "RED" if red_won else ("BLUE" if not draw else "DRAW")
        evs = [self._ev("WINDOW_CONTEST_END", rnd, contestId=cid, contestType=ctype,
                        winnerTeamId=winner_team, redPoint=c["redPoint"], bluePoint=c["bluePoint"])]
        self.contest_by_object.pop(c["object_key"], None)
        if red_won:
            if ctype == "RESOURCE":
                if self.stock.get(node, {}).get(target, 0) > 0:
                    self.stock[node][target] -= 1
                    self.inv[target] = self.inv.get(target, 0) + 1
                    evs.append(self._ev("RESOURCE_CLAIM", rnd, nodeId=node, resourceType=target))
                evs.append(self._ev("RESOURCE_CONTEST_WIN", rnd, contestId=cid, nodeId=node))
            elif ctype == "TASK":
                t = self._find_task(target)
                if t and not t["completed"]:
                    self._start_read("TASK", t["processRound"], t["taskId"], "PROCESSING")
                evs.append(self._ev("TASK_CONTEST_WIN", rnd, contestId=cid, taskId=target))
        else:
            # 蓝方胜或平局：蓝方取走对象（红方不可再领/做）
            if ctype == "RESOURCE":
                if self.stock.get(node, {}).get(target, 0) > 0:
                    self.stock[node][target] = 0
            elif ctype == "TASK":
                t = self._find_task(target)
                if t and not t["completed"]:
                    t["completed"] = True
        return evs

    # ---- 蓝方出牌（虚拟对手）----

    def _blue_choose(self, c, ri):
        """蓝方出牌策略：第 1 拍出 BING 试探，后续拍弃权让出。

        刻意偏弱（试一拍即让）以保交付稳定——目标是端到端跑通红方窗口逻辑（领出/反制/成本扣减/
        揭示读取/胜负授予），而非制造强对手。真机对手更强；如需压测红方败路，改为每拍出 BING。
        """
        if ri == 1 and self.blue["guard"] > 0:
            return "BING_ZHENG"
        return "ABSTAIN"

    def _blue_avail(self, stakes):
        """蓝方可用牌（镜像客户端 _available_cards 的成本门控）。"""
        b = self.blue
        avail = []
        if stakes >= 2 and b["guard"] > 0:
            avail.append("BING_ZHENG")
        if stakes >= 2 and b["fresh"] >= 80 and b["good"] >= 2:
            avail.append("XIAN_GONG")
        if b["permit"] > 0:
            avail.append("YAN_DIE")
        if b["horse"] > 0:
            avail.append("QIANG_XING")
        return avail

    # ---- 牌成本扣减（服务端权威，反映到下一帧 snapshot）----

    def _deduct_red_card(self, card):
        if card == "BING_ZHENG" and self.guard_ap > 0:
            self.guard_ap -= 1
        elif card == "XIAN_GONG" and self.good >= 1:
            self.good -= 1
        elif card == "QIANG_XING":
            if not self._has_move_buff():  # 已有移动增益时免消耗（§5.4.3）
                for h in ("FAST_HORSE", "SHORT_HORSE"):
                    if self.inv.get(h, 0) > 0:
                        self.inv[h] -= 1
                        break
        elif card == "YAN_DIE":
            for p in ("PASS_TOKEN", "OFFICIAL_PERMIT"):
                if self.inv.get(p, 0) > 0:
                    self.inv[p] -= 1
                    break

    def _deduct_blue_card(self, card):
        b = self.blue
        if card == "BING_ZHENG" and b["guard"] > 0:
            b["guard"] -= 1
        elif card == "XIAN_GONG" and b["good"] >= 1:
            b["good"] -= 1
        elif card == "QIANG_XING" and b["horse"] > 0:
            b["horse"] -= 1
        elif card == "YAN_DIE" and b["permit"] > 0:
            b["permit"] -= 1

    def _use(self, main, rnd):
        res = main.get("resourceType")
        if res == "ICE_BOX" and self.inv.get("ICE_BOX", 0) > 0 and self.fresh > 0:
            self.fresh = min(100.0, self.fresh + 10)
            self.inv["ICE_BOX"] -= 1
            return [self._ev("RESOURCE_USE", rnd, resourceType="ICE_BOX")]
        if res in self.HORSE_DUR and self.inv.get(res, 0) > 0 and not self._has_move_buff():
            self.buffs.append({"type": res, "remainingRound": self.HORSE_DUR[res]})
            self.inv[res] -= 1
            return [self._ev("RESOURCE_USE", rnd, resourceType=res)]
        if res == "INTEL" and self.inv.get("INTEL", 0) > 0:
            tgt = main.get("targetNodeId")
            if tgt:
                self.inv["INTEL"] -= 1
                self.marks.setdefault(tgt, set()).add("RED")  # 情报即时落标记（无延迟）
                return [self._ev("RESOURCE_USE", rnd, resourceType="INTEL", targetNodeId=tgt),
                        self._ev("SCOUT_MARKER_ADD", rnd, nodeId=tgt, teamId="RED")]
        return []

    def _tick_buffs(self):
        for b in self.buffs:
            b["remainingRound"] -= 1
        self.buffs = [b for b in self.buffs if b["remainingRound"] > 0]

    def _has_buff(self, t):
        return any(b["type"] == t for b in self.buffs)

    def _has_move_buff(self):
        return any(b["type"] in ("FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED") for b in self.buffs)

    def _find_task(self, tid):
        for t in self.tasks:
            if t["taskId"] == tid:
                return t
        return None

    def _ev(self, etype, rnd, **payload):
        payload["playerId"] = self.me_id
        return {"type": etype, "round": rnd, "payload": payload}


def build_inquire(match_id, rnd, sim, blue_id, node_ids, events, last_action):
    ar = []
    for r in (sim.last_action_results or []):
        entry = {"round": rnd - 1, "playerId": sim.me_id, "action": r["action"],
                 "accepted": r["accepted"], "result": r["result"]}
        if not r["accepted"]:
            entry["errorCode"] = r["errorCode"]
        ar.append(entry)
    if not ar and last_action is not None:
        ar.append({"round": rnd - 1, "playerId": sim.me_id, "action": "WAIT",
                   "accepted": True, "result": "ACCEPTED"})
    return {"msg_name": "inquire", "msg_data": {
        "matchId": match_id, "round": rnd, "tick": rnd - 1, "phase": "RUSH" if sim.rush else "NORMAL",
        "players": [sim.snapshot(),
                    {"playerId": blue_id, "teamId": "BLUE", "state": "IDLE",
                     "currentNodeId": "S01", "delivered": False, "retired": False}],
        "nodes": sim.nodes_view(node_ids), "tasks": sim.tasks_view(),
        "bounties": [], "contests": sim.contests_view(sim.me_id, blue_id),
        "events": events, "actionResults": ar,
        "scorePreview": {"RED": 0, "BLUE": 0}}}


def build_over(match_id, rnd, sim, blue_id, reason):
    return {"msg_name": "over", "msg_data": {
        "matchId": match_id, "overRound": rnd,
        "resultType": "NORMAL" if sim.delivered else "DRAW", "overReason": reason,
        "winnerPlayerId": sim.me_id if sim.delivered else None,
        "players": [{"playerId": sim.me_id, "playerName": "mock-red", "online": True, "delivered": sim.delivered,
                     "retired": False, "freshness": round(sim.fresh, 3), "goodFruit": sim.good,
                     "taskScore": sim.task_score, "deliverRound": rnd if sim.delivered else 0,
                     "totalScore": 0, "scoreDetail": {"total": 0}},
                    {"playerId": blue_id, "playerName": "mock-blue", "online": True, "delivered": False,
                     "retired": False, "totalScore": 0, "scoreDetail": {"total": 0}}]}}


def serve(host, port, max_rounds):
    mc = load_map()
    node_ids = [n["nodeId"] for n in mc["nodes"]]
    match_id, blue_id = "mock_match_001", 9999
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    print("[mock] listening on %s:%d (maxRounds=%d) obstacles=%s" % (host, port, max_rounds, OBSTACLES))
    conn, addr = srv.accept()
    print("[mock] client connected from %s" % (addr,))
    buf = bytearray()
    try:
        reg, buf = recv_one(conn, buf)
        if reg is None:
            return
        me_id = reg["msg_data"]["playerId"]
        print("[mock] <- registration playerId=%s" % me_id)
        conn.sendall(encode(build_start(mc, match_id, me_id, blue_id)))
        ready, buf = recv_one(conn, buf)
        if ready is None:
            return
        print("[mock] -> start; <- ready")

        sim = Sim(mc, me_id)
        pending, last_action, last_key = [], None, None
        for rnd in range(1, max_rounds + 1):
            conn.sendall(encode(build_inquire(match_id, rnd, sim, blue_id, node_ids, pending, last_action)))
            pending = []
            act_msg, buf = recv_one(conn, buf)
            if act_msg is None:
                print("[mock] client closed at round %d" % rnd)
                return
            actions = act_msg["msg_data"].get("actions", [])
            last_action = actions
            pending = sim.resolve(actions, rnd)
            rej = [(r["action"], r.get("errorCode")) for r in sim.last_action_results if not r["accepted"]]
            if rej:
                print("[mock] r%-3d REJECT %s" % (rnd, ",".join("%s:%s" % (a, c) for a, c in rej)))
            key = (sim.state, sim.pos, sim.verified, sim.task_score, tuple(sorted(sim.obstacles)))
            if key != last_key or pending:
                names = [e["type"] for e in pending]
                acts = ",".join(a.get("action", "?") for a in actions) or "[]"
                print("[mock] r%-3d pos=%-4s state=%-11s ver=%-5s task=%-3d good=%d inv=%s act=%-22s ev=%s"
                      % (rnd, sim.pos, sim.state, sim.verified, sim.task_score, sim.good,
                         dict((k, v) for k, v in sim.inv.items() if v), acts, names))
                last_key = key
            if sim.delivered:
                conn.sendall(encode(build_over(match_id, rnd, sim, blue_id, "ALL_DELIVERED")))
                print("[mock] -> over DELIVER_SUCCESS @r%d fresh=%.2f good=%d taskScore=%d"
                      % (rnd, sim.fresh, sim.good, sim.task_score))
                return
        conn.sendall(encode(build_over(match_id, max_rounds, sim, blue_id, "TIME_LIMIT")))
        print("[mock] -> over TIME_LIMIT pos=%s state=%s task=%d" % (sim.pos, sim.state, sim.task_score))
    finally:
        conn.close()
        srv.close()


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8081
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    serve(host, port, rounds)
