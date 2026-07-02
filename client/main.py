"""客户端入口：组装 registration -> start -> ready -> inquire/action 循环 -> over。

启动：python3 main.py <playerId> <host> <port>
（平台通过 start.sh 传入这三个参数；也容忍 --playerId= --host= --port= 形式。）

健壮性优先：任何单帧异常/超时都发出合法心跳（空 actions），杜绝连续缺动作退赛。
"""

import os
import sys
import time

# 确保 client/ 在 import 路径上（无论从何处启动）。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from communication.tcp_client import TcpClient  # noqa: E402
from logger.match_logger import MatchLogger  # noqa: E402
from protocol import messages  # noqa: E402
from protocol.enums import MsgName  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402


def parse_args(argv):
    """解析 playerId / host / port。支持位置参数与 --key=value / --key value。"""
    positional = []
    flags = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--"):
            body = tok[2:]
            if "=" in body:
                k, v = body.split("=", 1)
                flags[k.lower()] = v
            elif i + 1 < len(argv):
                flags[body.lower()] = argv[i + 1]
                i += 1
        else:
            positional.append(tok)
        i += 1

    def pick(name, idx):
        if name in flags:
            return flags[name]
        if idx < len(positional):
            return positional[idx]
        return None

    player_id = pick("playerid", 0)
    host = pick("host", 1)
    port = pick("port", 2)
    if player_id is None or host is None or port is None:
        raise SystemExit("Usage: main.py <playerId> <host> <port>")
    return int(player_id), host, int(port)


def resolve_log_dir():
    """把 config.LOG_DIR 解析为项目根（client 的上一级）下的 logs/。"""
    if os.path.isabs(config.LOG_DIR):
        return config.LOG_DIR
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, config.LOG_DIR)


def wait_for(client, want_name, timeout, logger):
    """在 timeout 秒内等待某类下行消息；期间对 error 记录并继续等待。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = client.recv(config.RECV_LOOP_TIMEOUT)
        if msg is None:
            if client.recv_ended.is_set():
                return None
            continue
        name = messages.msg_name(msg)
        if name == want_name:
            return msg
        if name == MsgName.ERROR:
            logger.log("error", msg="error", payload=messages.msg_data(msg))
        else:
            logger.log("recv", msg=name, note="unexpected_before_%s" % want_name)
    return None


def summarize_over(data):
    return {
        "resultType": data.get("resultType"),
        "overReason": data.get("overReason"),
        "overRound": data.get("overRound"),
        "winnerPlayerId": data.get("winnerPlayerId"),
        "players": [
            {"playerId": p.get("playerId"), "totalScore": p.get("totalScore"),
             "delivered": p.get("delivered"), "retired": p.get("retired")}
            for p in (data.get("players") or [])
        ],
    }


def run_loop(client, engine, logger, match_id, player_id):
    """主帧循环：处理 inquire / over / error。"""
    while True:
        msg = client.recv(config.RECV_LOOP_TIMEOUT)
        if msg is None:
            if client.recv_ended.is_set():
                logger.log("error", error="disconnected",
                           detail=str(client.error) if client.error else None)
                return
            continue  # 超时，服务端尚未下发，继续等待

        name = messages.msg_name(msg)
        data = messages.msg_data(msg)

        if name == MsgName.INQUIRE:
            _handle_inquire(client, engine, logger, match_id, player_id, data)
        elif name == MsgName.OVER:
            logger.log("recv", msg="over", payload=summarize_over(data))
            return
        elif name == MsgName.ERROR:
            logger.log("error", msg="error", payload=data)
        else:
            logger.log("recv", msg=name, note="unexpected_in_loop")


def _handle_inquire(client, engine, logger, match_id, player_id, data):
    rnd = data.get("round")
    logger.log("recv", round=rnd, msg="inquire", phase=data.get("phase"))

    t0 = time.perf_counter()
    try:
        actions = engine.decide(data)
    except Exception as exc:  # 决策异常绝不能拖垮心跳
        actions = []
        logger.log("error", round=rnd, error="decide_exception", detail=repr(exc))
    elapsed = time.perf_counter() - t0
    if elapsed > config.DECISION_BUDGET:
        logger.log("state", round=rnd, warn="decision_over_budget",
                   ms=round(elapsed * 1000, 1))

    try:
        client.send(messages.build_action(match_id, rnd, player_id, actions))
    except OSError as exc:
        logger.log("error", round=rnd, error="send_failed", detail=str(exc))
        return
    logger.log("decide", round=rnd, actions=actions, ms=round(elapsed * 1000, 1))


def main(argv):
    player_id, host, port = parse_args(argv)
    logger = MatchLogger(resolve_log_dir(), player_id)
    logger.log("state", note="startup", playerId=player_id, host=host, port=port,
               version=config.CLIENT_VERSION)

    client = TcpClient(host, port, logger)
    try:
        client.connect(config.CONNECT_TIMEOUT)
    except OSError as exc:
        logger.log("error", error="connect_failed", detail=str(exc))
        logger.close()
        return 1

    try:
        # 1) registration
        client.send(messages.build_registration(
            player_id, config.DEFAULT_PLAYER_NAME, config.CLIENT_VERSION))
        logger.log("send", msg="registration", playerId=player_id)

        # 2) start
        start = wait_for(client, MsgName.START, config.HANDSHAKE_TIMEOUT, logger)
        if start is None:
            logger.log("error", error="no_start_received")
            return 1
        sdata = messages.msg_data(start)
        match_id = sdata.get("matchId")
        logger.bind_match(match_id or "unknown")
        team_id, camp = messages.find_self_player(sdata, player_id)
        logger.log("recv", msg="start", matchId=match_id, teamId=team_id, camp=camp,
                   durationRound=sdata.get("durationRound"),
                   nodes=len(sdata.get("nodes", []) or []),
                   edges=len(sdata.get("edges", []) or []))

        # 3) ready（round 用 start.round，通常为 1）
        ready_round = sdata.get("round") or 1
        client.send(messages.build_ready(match_id, ready_round, player_id))
        logger.log("send", msg="ready", round=ready_round)

        # 4) 主循环
        ctx = GameContext(player_id, team_id, camp, sdata)
        engine = DecisionEngine(ctx)
        run_loop(client, engine, logger, match_id, player_id)
        return 0
    finally:
        client.close()
        logger.log("state", note="shutdown")
        logger.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
