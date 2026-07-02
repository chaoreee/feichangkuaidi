"""本地假服务端（开发工具，非提交物）——全流程仿真（M5 版）。

加载 samples/map_config.json 构建 start；模拟移动/处理/验核/交付 + M4 收益(资源/任务/急策) +
M5 对抗联调：道路障碍与主车队清障(CLEAR)、小分队探路(SQUAD_SCOUT)与宫门验核减时。

为验证突破逻辑，默认在 S13（终段唯一通路，不可绕行）放置一个道路障碍，迫使客户端 CLEAR。

简化口径（仅联调）：MOVE 占 2 帧；各读条占其帧数；CLEAR 占 6 帧且耗 1 好果；到 S14 触发 RUSH；
小分队探路 3 帧后在目标落下己方标记；验核时若宫门有己方标记则读条 -3（最低3）并消耗标记；
鲜度每帧 -0.05（护果令 ×0.2）；马/疾行仅登记 buff。

用法：python scripts/mock_server.py [host] [port] [maxRounds]（默认 127.0.0.1:8081, 250 帧）。
"""

import json
import os
import socket
import sys

W = 5
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAP = os.path.join(_ROOT, "samples", "map_config.json")

OBSTACLES = {"S13"}  # 终段唯一通路上的障碍：不可绕行 → 迫使客户端突破(CLEAR)
TASKS = [
    {"taskId": "TK1", "taskTemplateId": "T01", "name": "限时过关", "nodeId": "S09", "score": 30, "processRound": 3},
    {"taskId": "TK2", "taskTemplateId": "T02", "name": "抵驿催运", "nodeId": "S11", "score": 30, "processRound": 4},
    {"taskId": "TK3", "taskTemplateId": "T01", "name": "限时过关", "nodeId": "S13", "score": 30, "processRound": 3},
]


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


def build_adjacency(edges):
    adj = {}
    for e in edges:
        a, b = e["fromNodeId"], e["toNodeId"]
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return adj


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
        "taskTemplates": [{"taskTemplateId": "T01", "score": 30}, {"taskTemplateId": "T02", "score": 30}]}}


class Sim:
    HORSE_DUR = {"FAST_HORSE": 20, "SHORT_HORSE": 14}
    SCOUT_DELAY = 3

    def __init__(self, mc, me_id):
        self.me_id = me_id
        self.adj = build_adjacency(mc["edges"])
        self.proc_round = {p["nodeId"]: p["processRound"] for p in mc["processNodes"]}
        self.gate, self.terminal = "S14", "S15"
        self.verify_round = self.proc_round.get("S14", 6)
        self.stock = {}
        for r in mc.get("visibleResources", []):
            self.stock.setdefault(r["nodeId"], {}).setdefault(r["resourceType"], 0)
            self.stock[r["nodeId"]][r["resourceType"]] += 1
        self.tasks = [dict(t, completed=False) for t in TASKS]
        self.obstacles = set(OBSTACLES)
        self.marks = {}          # node -> set(teamId)
        self.pending_scouts = []  # [arrive_round, node, team]
        self.pending_clears = []  # [arrive_round, node]（小分队清障延迟落地）
        self.pos, self.state, self.target = "S01", "IDLE", None
        self.reading, self.read_kind, self.read_ctx, self.timer = False, None, None, 0
        self.verified = self.delivered = False
        self.good, self.fresh, self.rush = 100, 100.0, False
        self.inv, self.buffs, self.rush_used, self.task_score = {}, [], 0, 0
        self.squad_available = 8

    # ---- 快照 ----
    def snapshot(self):
        return {"playerId": self.me_id, "teamId": "RED", "state": self.state,
                "currentNodeId": self.pos, "nextNodeId": self.target,
                "freshness": round(self.fresh, 3), "goodFruit": self.good, "badFruit": 0, "frozenGoodFruit": 0,
                "squadAvailable": self.squad_available, "guardActionPoint": 4,
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
            out.append({"nodeId": nid, "resourceStock": dict(self.stock.get(nid, {})),
                        "hasObstacle": nid in self.obstacles, "obstacleType": "ROCKFALL" if nid in self.obstacles else None,
                        "scouted": scouted, "canWindow": False})
        return out

    # ---- 推进 ----
    def resolve(self, actions, rnd):
        events = []
        main = next((a for a in actions if not str(a.get("action", "")).startswith("SQUAD_")), None)
        squad = next((a for a in actions if str(a.get("action", "")).startswith("SQUAD_")), None)
        act = main.get("action") if main else None

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
            events += self._apply_idle(act, main, rnd)

        if squad:
            events += self._apply_squad(squad, rnd)
        events += self._deliver_scouts(rnd)
        events += self._deliver_clears(rnd)

        self._tick_buffs()
        fmult = 0.2 if self._has_buff("RUSH_PROTECT") else 1.0
        if self._has_buff("RUSH_SPEED"):
            fmult *= 1.25
        self.fresh = max(0.0, self.fresh - 0.05 * fmult)
        return events

    def _apply_idle(self, act, main, rnd):
        events = []
        if act == "MOVE":
            tgt = main.get("targetNodeId")
            if tgt in self.adj.get(self.pos, ()) and tgt not in self.obstacles:
                self.state, self.target, self.timer = "MOVING", tgt, 1
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
            if node == self.pos and self.stock.get(self.pos, {}).get(res, 0) > 0:
                self._start_read("CLAIM", 2, res, "PROCESSING")
        elif act == "CLAIM_TASK":
            t = self._find_task(main.get("taskId"))
            if t and not t["completed"] and t["nodeId"] == self.pos:
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
        if a in ("SQUAD_WEAKEN", "SQUAD_REINFORCE") and self.squad_available >= 2 and tgt:
            self.squad_available -= 2  # 本 mock 无敌方设卡，接受并记消耗
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
        self.timer -= 1
        if self.timer <= 0:
            self.pos, self.target, self.state = self.target, None, "IDLE"
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
            return [self._ev("TASK_COMPLETE", rnd, taskId=ctx, score=t["score"], taskScore=self.task_score)]
        return []

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
    if last_action is not None:
        first = last_action[0]["action"] if last_action else "WAIT"
        ar.append({"round": rnd - 1, "playerId": sim.me_id, "action": first, "accepted": True, "result": "ACCEPTED"})
    return {"msg_name": "inquire", "msg_data": {
        "matchId": match_id, "round": rnd, "tick": rnd - 1, "phase": "RUSH" if sim.rush else "NORMAL",
        "players": [sim.snapshot(),
                    {"playerId": blue_id, "teamId": "BLUE", "state": "IDLE",
                     "currentNodeId": "S01", "delivered": False, "retired": False}],
        "nodes": sim.nodes_view(node_ids), "tasks": sim.tasks_view(),
        "bounties": [], "contests": [], "events": events, "actionResults": ar,
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
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 250
    serve(host, port, rounds)
