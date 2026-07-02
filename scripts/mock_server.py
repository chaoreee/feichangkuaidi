"""本地假服务端（开发工具，非提交物）。

用最小但协议合法的下发跑通 registration -> start -> ready -> inquire/action 循环 -> over，
用于离线验证客户端的通信闭环与心跳健壮性。地图取自协议附录 A 默认地图（可变项占位）。

用法：
    python scripts/mock_server.py [host] [port] [rounds]
默认 127.0.0.1:8081，跑 15 个结算帧后下发 over。

自包含：内联极简 framing，不依赖 client 包。
"""

import json
import socket
import sys

W = 5  # 长度前缀宽度


def encode(envelope):
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return str(len(body)).zfill(W).encode("ascii") + body


def recv_one(sock, buf):
    """阻塞读出一条完整消息 dict；返回 (message, buf) 或 (None, buf) 表示对端关闭。"""
    while True:
        if len(buf) >= W and buf[:W].isdigit():
            length = int(buf[:W])
            total = W + length
            if len(buf) >= total:
                body = bytes(buf[W:total])
                del buf[:total]
                return json.loads(body.decode("utf-8")), buf
        chunk = sock.recv(65536)
        if not chunk:
            return None, buf
        buf.extend(chunk)


# ---- 默认地图（协议附录 A；正式对战以服务端 start 实际下发为准）----

NODES = [
    {"nodeId": "S01", "name": "岭南果园", "x": 5, "y": 50, "nodeType": "START", "start": True, "terminal": False},
    {"nodeId": "S02", "name": "南岭驿", "x": 14, "y": 46, "nodeType": "CHECKPOINT"},
    {"nodeId": "S03", "name": "梅关驿", "x": 22, "y": 42, "nodeType": "PASS"},
    {"nodeId": "S04", "name": "江南码头", "x": 20, "y": 54, "nodeType": "DOCK"},
    {"nodeId": "S05", "name": "洞庭水驿", "x": 34, "y": 52, "nodeType": "WATER_STATION"},
    {"nodeId": "S06", "name": "五岭山道", "x": 26, "y": 34, "nodeType": "MOUNTAIN_NODE"},
    {"nodeId": "S07", "name": "荆襄大驿", "x": 42, "y": 42, "nodeType": "STATION"},
    {"nodeId": "S08", "name": "秦岭栈道", "x": 44, "y": 30, "nodeType": "MOUNTAIN_PASS"},
    {"nodeId": "S09", "name": "洛阳驿", "x": 56, "y": 44, "nodeType": "STATION"},
    {"nodeId": "S10", "name": "武关", "x": 60, "y": 34, "nodeType": "KEY_PASS"},
    {"nodeId": "S11", "name": "潼关驿", "x": 66, "y": 30, "nodeType": "PASS"},
    {"nodeId": "S12", "name": "关中平原", "x": 70, "y": 24, "nodeType": "JUNCTION"},
    {"nodeId": "S13", "name": "灞桥驿", "x": 73, "y": 20, "nodeType": "PALACE_STATION"},
    {"nodeId": "S14", "name": "朱雀门", "x": 76, "y": 18, "nodeType": "GATE"},
    {"nodeId": "S15", "name": "兴庆宫", "x": 78, "y": 18, "nodeType": "FINISH", "terminal": True},
]

EDGES = [
    ("E01", "S01", "S02", "ROAD", 30), ("E02", "S02", "S03", "ROAD", 25),
    ("E03", "S03", "S07", "ROAD", 54), ("E04", "S07", "S09", "ROAD", 46),
    ("E05", "S09", "S10", "ROAD", 40), ("E06", "S10", "S11", "ROAD", 36),
    ("E07", "S11", "S12", "ROAD", 20), ("E08", "S12", "S13", "ROAD", 25),
    ("E09", "S13", "S14", "ROAD", 18), ("E10", "S14", "S15", "ROAD", 10),
    ("E11", "S02", "S04", "ROAD", 20), ("E12", "S04", "S05", "WATER", 44),
    ("E13", "S05", "S07", "BRANCH", 46), ("E15", "S01", "S06", "MOUNTAIN", 44),
    ("E16", "S06", "S08", "MOUNTAIN", 54), ("E17", "S08", "S10", "BRANCH", 46),
    ("E18", "S03", "S06", "BRANCH", 38), ("E19", "S05", "S09", "WATER", 48),
    ("E20", "S07", "S08", "MOUNTAIN", 42), ("E21", "S04", "S07", "BRANCH", 54),
    ("E22", "S08", "S09", "BRANCH", 64),
]


def build_edges():
    return [
        {"edgeId": e, "fromNodeId": a, "toNodeId": b, "fromNode": a, "toNode": b,
         "routeType": t, "distance": d, "bidirectional": True}
        for (e, a, b, t, d) in EDGES
    ]


def build_start(match_id, red_player_id, blue_player_id):
    return {
        "msg_name": "start",
        "msg_data": {
            "matchId": match_id,
            "rulesVersion": "mock",
            "round": 1,
            "tick": 0,
            "durationRound": 600,
            "map": {
                "mapId": "mock_map",
                "maxX": 80, "maxY": 60,
                "gameplay": {
                    "roles": {
                        "startNodeId": "S01",
                        "gateNodeId": "S14",
                        "terminalNodeIds": ["S15"],
                        "safeZoneNodeIds": ["S15"],
                    },
                    "resources": [],
                    "processNodes": [
                        {"nodeId": "S04", "processType": "BOARD", "processRound": 7, "canWindow": True},
                        {"nodeId": "S14", "processType": "VERIFY", "processRound": 6, "canWindow": True},
                    ],
                    "taskCandidates": {},
                    "routeTaskBuckets": {},
                    "obstacleCandidateNodeIds": ["S06", "S08", "S10", "S11"],
                },
            },
            "players": [
                {"playerId": red_player_id, "camp": 0, "teamId": "RED", "name": "mock-red"},
                {"playerId": blue_player_id, "camp": 1, "teamId": "BLUE", "name": "mock-blue"},
            ],
            "nodes": NODES,
            "edges": build_edges(),
            "resources": [
                {"nodeId": "S09", "resourceType": "FAST_HORSE", "count": 1, "claimRound": 2},
                {"nodeId": "S04", "resourceType": "SHORT_HORSE", "count": 1, "claimRound": 2},
            ],
            "taskTemplates": [
                {"taskTemplateId": "T01", "name": "限时过关", "processType": "REACH",
                 "processRound": 3, "score": 30, "candidateNodeIds": ["S03"]},
            ],
        },
    }


def build_inquire(match_id, rnd, me_id, opp_id, last_action):
    """构造一帧 inquire。me 在 S01 IDLE，鲜度随帧数缓降。"""
    action_results = []
    if last_action is not None:
        action_results.append({
            "round": rnd - 1, "playerId": me_id,
            "action": (last_action[0]["action"] if last_action else "WAIT"),
            "accepted": True, "result": "ACCEPTED",
        })
    return {
        "msg_name": "inquire",
        "msg_data": {
            "matchId": match_id,
            "round": rnd,
            "tick": rnd - 1,
            "phase": "NORMAL",
            "players": [
                {"playerId": me_id, "teamId": "RED", "state": "IDLE",
                 "currentNodeId": "S01", "nextNodeId": None,
                 "freshness": max(0.0, 100.0 - 0.05 * (rnd - 1)),
                 "goodFruit": 100, "badFruit": 0, "frozenGoodFruit": 0,
                 "squadAvailable": 8, "guardActionPoint": 4,
                 "verified": False, "delivered": False, "retired": False,
                 "resources": {}, "taskScore": 0, "bountyScore": 0, "totalScore": 0},
                {"playerId": opp_id, "teamId": "BLUE", "state": "IDLE",
                 "currentNodeId": "S01", "delivered": False, "retired": False},
            ],
            "nodes": [{"nodeId": "S01", "resourceStock": {}, "hasObstacle": False, "canWindow": False}],
            "tasks": [],
            "bounties": [],
            "contests": [],
            "events": [],
            "actionResults": action_results,
            "scorePreview": {"RED": 0, "BLUE": 0},
        },
    }


def build_over(match_id, over_round, me_id, opp_id):
    return {
        "msg_name": "over",
        "msg_data": {
            "matchId": match_id,
            "overRound": over_round,
            "resultType": "DRAW",
            "overReason": "TIME_LIMIT",
            "winnerPlayerId": None,
            "players": [
                {"playerId": me_id, "playerName": "mock-red", "online": True,
                 "delivered": False, "retired": False, "totalScore": 0,
                 "scoreDetail": {"total": 0}},
                {"playerId": opp_id, "playerName": "mock-blue", "online": True,
                 "delivered": False, "retired": False, "totalScore": 0,
                 "scoreDetail": {"total": 0}},
            ],
        },
    }


def serve(host, port, rounds):
    match_id = "mock_match_001"
    opp_id = 9999
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    print("[mock] listening on %s:%d (rounds=%d)" % (host, port, rounds))
    conn, addr = srv.accept()
    print("[mock] client connected from %s" % (addr,))
    buf = bytearray()
    try:
        # registration
        reg, buf = recv_one(conn, buf)
        if reg is None:
            print("[mock] client closed before registration"); return
        me_id = reg["msg_data"]["playerId"]
        print("[mock] <- registration playerId=%s name=%s" % (me_id, reg["msg_data"].get("playerName")))

        # start
        conn.sendall(encode(build_start(match_id, me_id, opp_id)))
        print("[mock] -> start")

        # ready
        ready, buf = recv_one(conn, buf)
        if ready is None:
            print("[mock] client closed before ready"); return
        print("[mock] <- ready round=%s" % ready["msg_data"].get("round"))

        # inquire / action 循环
        last_action = None
        for rnd in range(1, rounds + 1):
            conn.sendall(encode(build_inquire(match_id, rnd, me_id, opp_id, last_action)))
            act, buf = recv_one(conn, buf)
            if act is None:
                print("[mock] client closed at round %d" % rnd); return
            a = act["msg_data"]
            assert a["round"] == rnd, "round mismatch: got %s want %d" % (a["round"], rnd)
            last_action = a.get("actions", [])
            print("[mock] <- action round=%d actions=%s" % (rnd, last_action))

        # over
        conn.sendall(encode(build_over(match_id, rounds, me_id, opp_id)))
        print("[mock] -> over (resultType=DRAW). Done.")
    finally:
        conn.close()
        srv.close()


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8081
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    serve(host, port, rounds)
