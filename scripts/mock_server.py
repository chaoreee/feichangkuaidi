"""本地假服务端（开发工具，非提交物）——全流程仿真。

加载 samples/map_config.json 构建 start；模拟单个客户端主车队的移动/固定处理/宫门验核/交付，
用于离线验证 M3 基线策略能否走完 registration -> 推进 -> 处理 -> 验核 -> 交付 -> over。

简化口径（仅为联调，非真实结算）：
- MOVE：占 2 帧（发起 1 帧 + 在途 1 帧）到达相邻节点。
- PROCESS：占 processRound 帧读条。
- VERIFY_GATE：仅在 RUSH 且位于宫门时可提交，占宫门 processRound 帧。
- 到达宫门 S14 即进入 RUSH（模拟"到位触发冲刺"）。
- 鲜度每帧 -0.05。交付成功即下发 over。

用法：python scripts/mock_server.py [host] [port] [maxRounds]
默认 127.0.0.1:8081，最多 150 帧。
"""

import json
import os
import socket
import sys

W = 5
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAP = os.path.join(_ROOT, "samples", "map_config.json")


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
        adj.setdefault(b, set()).add(a)  # map_config 无方向字段，按双向
    return adj


def build_start(mc, match_id, red_id, blue_id):
    return {
        "msg_name": "start",
        "msg_data": {
            "matchId": match_id, "rulesVersion": "mock", "round": 1, "tick": 0,
            "durationRound": 600,
            "map": {"maxX": mc["map"]["maxX"], "maxY": mc["map"]["maxY"],
                    "gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14",
                                           "terminalNodeIds": ["S15"], "safeZoneNodeIds": ["S15"]}}},
            "players": [
                {"playerId": red_id, "camp": 0, "teamId": "RED", "name": "mock-red"},
                {"playerId": blue_id, "camp": 1, "teamId": "BLUE", "name": "mock-blue"},
            ],
            "nodes": mc["nodes"],
            "edges": mc["edges"],
            "processNodes": mc["processNodes"],
            "resources": [{"nodeId": r["nodeId"], "resourceType": r["resourceType"],
                           "count": 1, "claimRound": 2} for r in mc.get("visibleResources", [])],
            "taskTemplates": [],
        },
    }


class Sim:
    """单个主车队的最小状态机。"""

    def __init__(self, mc, me_id):
        self.me_id = me_id
        self.adj = build_adjacency(mc["edges"])
        self.proc_round = {p["nodeId"]: p["processRound"] for p in mc["processNodes"]}
        self.gate = "S14"
        self.terminal = "S15"
        self.verify_round = self.proc_round.get(self.gate, 6)
        # 状态
        self.pos = "S01"
        self.state = "IDLE"
        self.target = None
        self.timer = 0
        self.verified = False
        self.delivered = False
        self.good = 100
        self.fresh = 100.0
        self.rush = False

    def snapshot(self):
        return {
            "playerId": self.me_id, "teamId": "RED", "state": self.state,
            "currentNodeId": self.pos, "nextNodeId": self.target,
            "freshness": round(self.fresh, 3), "goodFruit": self.good, "badFruit": 0,
            "frozenGoodFruit": 0, "squadAvailable": 8, "guardActionPoint": 4,
            "verified": self.verified, "delivered": self.delivered, "retired": False,
            "resources": {}, "taskScore": 0, "bountyScore": 0, "totalScore": 0,
        }

    def resolve(self, actions, rnd):
        """应用本帧动作并推进一拍，返回本帧产生的事件列表。"""
        events = []
        main = actions[0] if actions else None
        act = main.get("action") if main else None

        if self.state in ("IDLE", "COST_BANKRUPT"):
            if act == "MOVE":
                tgt = main.get("targetNodeId")
                if tgt in self.adj.get(self.pos, ()):  # 相邻才允许
                    self.state, self.target, self.timer = "MOVING", tgt, 1
            elif act == "PROCESS":
                if self.pos in self.proc_round:
                    self.state, self.timer = "PROCESSING", self.proc_round[self.pos]
            elif act == "VERIFY_GATE":
                if self.rush and self.pos == self.gate and not self.verified:
                    self.state, self.timer = "VERIFYING", self.verify_round
            elif act == "DELIVER":
                if self.pos == self.terminal and self.verified and self.good > 0 and self.fresh > 0:
                    self.delivered = True
                    events.append(self._ev("DELIVER_SUCCESS", rnd))
        elif self.state == "MOVING":
            self.timer -= 1
            if self.timer <= 0:
                self.pos, self.target, self.state = self.target, None, "IDLE"
                events.append(self._ev("NODE_ENTER", rnd, nodeId=self.pos))
                if self.pos == self.gate:
                    self.rush = True
                    events.append(self._ev("RUSH_START", rnd))
        elif self.state == "PROCESSING":
            self.timer -= 1
            if self.timer <= 0:
                self.state = "IDLE"
                events.append(self._ev("PROCESS_COMPLETE", rnd, nodeId=self.pos))
        elif self.state == "VERIFYING":
            self.timer -= 1
            if self.timer <= 0:
                self.state, self.verified = "IDLE", True
                events.append(self._ev("VERIFY_GATE_COMPLETE", rnd))

        self.fresh = max(0.0, self.fresh - 0.05)
        return events

    def _ev(self, etype, rnd, **payload):
        payload["playerId"] = self.me_id
        return {"type": etype, "round": rnd, "payload": payload}


def build_inquire(match_id, rnd, sim, blue_id, events, last_action):
    phase = "RUSH" if sim.rush else "NORMAL"
    action_results = []
    if last_action is not None:
        first = last_action[0]["action"] if last_action else "WAIT"
        action_results.append({"round": rnd - 1, "playerId": sim.me_id,
                               "action": first, "accepted": True, "result": "ACCEPTED"})
    return {
        "msg_name": "inquire",
        "msg_data": {
            "matchId": match_id, "round": rnd, "tick": rnd - 1, "phase": phase,
            "players": [sim.snapshot(),
                        {"playerId": blue_id, "teamId": "BLUE", "state": "IDLE",
                         "currentNodeId": "S01", "delivered": False, "retired": False}],
            "nodes": [], "tasks": [], "bounties": [], "contests": [],
            "events": events, "actionResults": action_results,
            "scorePreview": {"RED": 0, "BLUE": 0},
        },
    }


def build_over(match_id, rnd, sim, blue_id, reason):
    return {
        "msg_name": "over",
        "msg_data": {
            "matchId": match_id, "overRound": rnd,
            "resultType": "NORMAL" if sim.delivered else "DRAW",
            "overReason": reason, "winnerPlayerId": sim.me_id if sim.delivered else None,
            "players": [
                {"playerId": sim.me_id, "playerName": "mock-red", "online": True,
                 "delivered": sim.delivered, "retired": False,
                 "freshness": round(sim.fresh, 3), "goodFruit": sim.good,
                 "deliverRound": rnd if sim.delivered else 0,
                 "totalScore": 0, "scoreDetail": {"total": 0}},
                {"playerId": blue_id, "playerName": "mock-blue", "online": True,
                 "delivered": False, "retired": False, "totalScore": 0, "scoreDetail": {"total": 0}},
            ],
        },
    }


def serve(host, port, max_rounds):
    mc = load_map()
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
        print("[mock] -> start")
        ready, buf = recv_one(conn, buf)
        if ready is None:
            return
        print("[mock] <- ready")

        sim = Sim(mc, me_id)
        pending, last_action, last_report = [], None, (None, None)
        for rnd in range(1, max_rounds + 1):
            conn.sendall(encode(build_inquire(match_id, rnd, sim, blue_id, pending, last_action)))
            pending = []
            act_msg, buf = recv_one(conn, buf)
            if act_msg is None:
                print("[mock] client closed at round %d" % rnd)
                return
            actions = act_msg["msg_data"].get("actions", [])
            last_action = actions
            pending = sim.resolve(actions, rnd)
            # 精简轨迹：状态或位置变化时打印
            report = (sim.state, sim.pos)
            if report != last_report or pending:
                names = [e["type"] for e in pending]
                print("[mock] r%-3d pos=%-4s state=%-11s verified=%s act=%s ev=%s"
                      % (rnd, sim.pos, sim.state, sim.verified,
                         (actions[0]["action"] if actions else "[]"), names))
                last_report = report
            if sim.delivered:
                conn.sendall(encode(build_over(match_id, rnd, sim, blue_id, "ALL_DELIVERED")))
                print("[mock] -> over DELIVER_SUCCESS @r%d fresh=%.2f good=%d" % (rnd, sim.fresh, sim.good))
                return
        conn.sendall(encode(build_over(match_id, max_rounds, sim, blue_id, "TIME_LIMIT")))
        print("[mock] -> over TIME_LIMIT (未交付) pos=%s state=%s" % (sim.pos, sim.state))
    finally:
        conn.close()
        srv.close()


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8081
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 150
    serve(host, port, rounds)
