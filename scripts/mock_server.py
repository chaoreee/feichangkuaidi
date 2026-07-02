"""本地假服务端（开发工具，非提交物）——全流程仿真（M4 版）。

加载 samples/map_config.json 构建 start；模拟主车队移动/固定处理/宫门验核/交付，
并支持 M4 交互：资源领取(CLAIM_RESOURCE)、皇榜任务(CLAIM_TASK)、资源使用(USE_RESOURCE，
冰鉴回鲜/马加 buff)、护果令(RUSH_PROTECT)。用于离线验证 M4 收益策略。

简化口径（仅联调，非真实结算）：MOVE 占 2 帧到相邻节点；各类读条占其帧数；到 S14 触发 RUSH；
鲜度每帧 -0.05（护果令生效 ×0.2）；马仅登记 buff 不改移动速度。

用法：python scripts/mock_server.py [host] [port] [maxRounds]（默认 127.0.0.1:8081, 200 帧）。
"""

import json
import os
import socket
import sys

W = 5
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAP = os.path.join(_ROOT, "samples", "map_config.json")

# 注入若干在"水路时间最优线"(S02→S04→S05→S09→S10→S11→S12→S13)上的任务，累计 90 分
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
    return {
        "msg_name": "start",
        "msg_data": {
            "matchId": match_id, "rulesVersion": "mock", "round": 1, "tick": 0, "durationRound": 600,
            "map": {"maxX": mc["map"]["maxX"], "maxY": mc["map"]["maxY"],
                    "gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14",
                                           "terminalNodeIds": ["S15"], "safeZoneNodeIds": ["S15"]}}},
            "players": [
                {"playerId": red_id, "camp": 0, "teamId": "RED", "name": "mock-red"},
                {"playerId": blue_id, "camp": 1, "teamId": "BLUE", "name": "mock-blue"},
            ],
            "nodes": mc["nodes"], "edges": mc["edges"], "processNodes": mc["processNodes"],
            "resources": [{"nodeId": r["nodeId"], "resourceType": r["resourceType"], "count": 1, "claimRound": 2}
                          for r in mc.get("visibleResources", [])],
            "taskTemplates": [{"taskTemplateId": "T01", "score": 30}, {"taskTemplateId": "T02", "score": 30}],
        },
    }


class Sim:
    HORSE_DUR = {"FAST_HORSE": 20, "SHORT_HORSE": 14}

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
        # 状态
        self.pos, self.state, self.target = "S01", "IDLE", None
        self.reading, self.read_kind, self.read_ctx, self.timer = False, None, None, 0
        self.verified = self.delivered = False
        self.good, self.fresh, self.rush = 100, 100.0, False
        self.inv, self.buffs, self.rush_used, self.task_score = {}, [], 0, 0

    # ---- 快照 ----
    def snapshot(self):
        return {
            "playerId": self.me_id, "teamId": "RED", "state": self.state,
            "currentNodeId": self.pos, "nextNodeId": self.target,
            "freshness": round(self.fresh, 3), "goodFruit": self.good, "badFruit": 0, "frozenGoodFruit": 0,
            "squadAvailable": 8, "guardActionPoint": 4, "verified": self.verified, "delivered": self.delivered,
            "retired": False, "resources": {k: v for k, v in self.inv.items() if v > 0},
            "buffs": [{"type": b["type"], "remainingRound": b["remainingRound"]} for b in self.buffs],
            "rushTacticUsedCount": self.rush_used, "taskScore": self.task_score,
            "bountyScore": 0, "totalScore": 0,
        }

    def tasks_view(self):
        return [{"taskId": t["taskId"], "taskTemplateId": t["taskTemplateId"], "name": t.get("name"),
                 "nodeId": t["nodeId"], "score": t["score"], "processRound": t["processRound"],
                 "active": not t["completed"], "completed": t["completed"], "failed": False}
                for t in self.tasks]

    def nodes_view(self, all_node_ids):
        return [{"nodeId": nid, "resourceStock": dict(self.stock.get(nid, {})),
                 "hasObstacle": False, "canWindow": False} for nid in all_node_ids]

    # ---- 推进 ----
    def resolve(self, actions, rnd):
        events = []
        main = actions[0] if actions else None
        act = main.get("action") if main else None

        if not self.reading and self.state == "MOVING":
            if act == "USE_RESOURCE":
                events += self._use(main, rnd)
            self.timer -= 1
            if self.timer <= 0:
                self.pos, self.target, self.state = self.target, None, "IDLE"
                events.append(self._ev("NODE_ENTER", rnd, nodeId=self.pos))
                if self.pos == self.gate and not self.rush:
                    self.rush = True
                    events.append(self._ev("RUSH_START", rnd))
        elif self.reading:
            self.timer -= 1
            if self.timer <= 0:
                events += self._finish_read(rnd)
        elif self.state in ("IDLE", "COST_BANKRUPT"):
            events += self._apply_idle(act, main, rnd)

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
            if tgt in self.adj.get(self.pos, ()):
                self.state, self.target, self.timer = "MOVING", tgt, 1
        elif act == "PROCESS":
            if self.pos in self.proc_round:
                self._start_read("PROCESS", self.proc_round[self.pos], None, "PROCESSING")
        elif act == "VERIFY_GATE":
            if self.rush and self.pos == self.gate and not self.verified:
                self._start_read("VERIFY", self.verify_round, None, "VERIFYING")
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
        elif act == "DELIVER":
            if self.pos == self.terminal and self.verified and self.good > 0 and self.fresh > 0:
                self.delivered = True
                events.append(self._ev("DELIVER_SUCCESS", rnd))
        return events

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
        if res == "ICE_BOX":
            if self.inv.get("ICE_BOX", 0) > 0 and self.fresh > 0:
                self.fresh = min(100.0, self.fresh + 10)
                self.inv["ICE_BOX"] -= 1
                return [self._ev("RESOURCE_USE", rnd, resourceType="ICE_BOX")]
        elif res in self.HORSE_DUR:
            if self.inv.get(res, 0) > 0 and not self._has_move_buff():
                self.buffs.append({"type": res, "remainingRound": self.HORSE_DUR[res]})
                self.inv[res] -= 1
                return [self._ev("RESOURCE_USE", rnd, resourceType=res)]
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
    phase = "RUSH" if sim.rush else "NORMAL"
    ar = []
    if last_action is not None:
        first = last_action[0]["action"] if last_action else "WAIT"
        ar.append({"round": rnd - 1, "playerId": sim.me_id, "action": first,
                   "accepted": True, "result": "ACCEPTED"})
    return {"msg_name": "inquire", "msg_data": {
        "matchId": match_id, "round": rnd, "tick": rnd - 1, "phase": phase,
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
        "players": [
            {"playerId": sim.me_id, "playerName": "mock-red", "online": True, "delivered": sim.delivered,
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
    print("[mock] listening on %s:%d (maxRounds=%d)" % (host, port, max_rounds))
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
            key = (sim.state, sim.pos, sim.verified, sim.task_score)
            if key != last_key or pending:
                names = [e["type"] for e in pending]
                print("[mock] r%-3d pos=%-4s state=%-11s ver=%-5s task=%-3d inv=%s act=%-14s ev=%s"
                      % (rnd, sim.pos, sim.state, sim.verified, sim.task_score,
                         dict((k, v) for k, v in sim.inv.items() if v),
                         (actions[0]["action"] if actions else "[]"), names))
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
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    serve(host, port, rounds)
