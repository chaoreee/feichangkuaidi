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
from core.world_state import WorldState  # noqa: E402


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
    """把 config.LOG_DIR 解析为 client/ 目录下的 logs/。

    client/ 本身即提交平台的交付件根目录，因此日志必须落在包内（client/logs/），
    对局结束后可随交付件一起下载回本地做分析。
    """
    if os.path.isabs(config.LOG_DIR):
        return config.LOG_DIR
    client_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(client_dir, config.LOG_DIR)


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
            _log_error(logger, None, messages.msg_data(msg))
        else:
            logger.trace("Recv", msg=name, note="unexpected_before_%s" % want_name)
    return None


def _log_over(logger, player_id, data):
    """把 over 结算写成一行 Over trace（本方结果 + 胜负），逐队再各写一行 Score。"""
    winner = data.get("winnerPlayerId")
    logger.trace(
        "Over", resultType=data.get("resultType"), reason=data.get("overReason"),
        overRound=data.get("overRound"), winner=winner,
        iWon=(str(winner) == str(player_id)) if winner is not None else None)
    for p in (data.get("players") or []):
        pid = p.get("playerId")
        logger.trace(
            "Score", player=pid, me=(str(pid) == str(player_id)),
            total=p.get("totalScore"), delivered=p.get("delivered"),
            deliverRound=p.get("deliverRound"), retired=p.get("retired"),
            fresh=p.get("freshness"), goodFruit=p.get("goodFruit"),
            taskScore=p.get("taskScore"), bountyScore=p.get("bountyScore"))


def _log_error(logger, rnd, payload):
    """把 error 载荷压平成一行 Error trace（code/reason/detail 尽量提取）。"""
    if isinstance(payload, dict):
        logger.trace(
            "Error", round=rnd, code=payload.get("errorCode") or payload.get("code"),
            reason=payload.get("reason") or payload.get("message"),
            detail=payload if not (payload.get("errorCode") or payload.get("code")) else None)
    else:
        logger.trace("Error", round=rnd, detail=payload)


def _action_fields(action):
    """从单个动作 dict 提取 trace 字段：action 类型 + 目标/参数（跳过空值）。"""
    fields = {"action": action.get("action")}
    for src, dst in (("targetNodeId", "target"), ("taskId", "task"),
                     ("resourceType", "resource"), ("contestId", "contest"),
                     ("card", "card"), ("rushTactic", "rush"),
                     ("goodFruit", "good"), ("badFruit", "bad"),
                     ("extraGoodFruit", "extraGood")):
        if action.get(src) is not None:
            fields[dst] = action[src]
    return fields


# ---- 日志字段构造器（纯函数，便于单测；None 字段由 logger 丢弃）----

def _fmt_opp(opp):
    """对手镜像打包：node|state|fresh|goodFruit|taskScore|verified|delivered；缺失段写 -。"""
    if opp is None:
        return "-"

    def g(v):
        if v is None:
            return "-"
        if isinstance(v, bool):
            return "T" if v else "F"
        if isinstance(v, float):
            return ("%.2f" % v).rstrip("0").rstrip(".")
        return str(v)

    return "|".join(g(x) for x in (
        opp.current_node_id, opp.state, opp.freshness,
        opp.good_fruit, opp.task_score, opp.verified, opp.delivered))


def frame_fields(rnd, data, world):
    """Frame 行字段：本方状态 + 天气 + 对手镜像 + 事件类型。"""
    me = world.me if world else None
    fields = {
        "round": rnd, "phase": data.get("phase"),
        "node": (me.current_node_id if me else None),
        "state": (me.state if me else None),
        "fresh": (me.freshness if me else None),
        "goodFruit": (me.good_fruit if me else None),
        "taskScore": (me.task_score if me else None),
        "verified": (me.verified if me else None),
        "delivered": (me.delivered if me else None),
    }
    if world is not None:
        w = world.active_weather_type()
        if w is not None:
            fields["weather"] = w
        opp = world.opponent
        if opp is not None:
            fields["opp"] = _fmt_opp(opp)
        evs = [e.get("type") for e in world.events]
        if evs:
            fields["events"] = evs
    return fields


def _block_signature(ns):
    """节点阻塞签名 (obstacle, guardOwner, guardDef)；无阻塞返回 None。"""
    obstacle = ns.obstacle_type if ns.has_obstacle else None
    owner = ns.active_guard_owner()
    if not obstacle and owner is None:
        return None
    guard_def = (ns.guard or {}).get("defense", 0) if owner is not None else 0
    return (obstacle, owner, guard_def)


def block_diff(world, prev_blocks):
    """对比上一帧阻塞快照，返回 (changed, cleared, current)。

    changed: [(nodeId, sig)] 新增或变化的阻塞；
    cleared: [nodeId] 上帧有本帧无（阻塞解除）；
    current: 本帧阻塞快照 dict，供下帧对比。
    """
    cur = {}
    if world is not None:
        for nid, ns in world.node_states.items():
            sig = _block_signature(ns)
            if sig is not None:
                cur[nid] = sig
    changed = [(n, s) for n, s in cur.items() if prev_blocks.get(n) != s]
    cleared = [n for n in prev_blocks if n not in cur]
    return changed, cleared, cur


def contest_fields(world, contest, player_id):
    """Contest 行字段：本方参与窗口的一拍快照。"""
    cid = contest.get("contestId")
    my_color = "RED" if contest.get("redPlayerId") == player_id else "BLUE"
    opp_color = "BLUE" if my_color == "RED" else "RED"
    if my_color == "RED":
        my_pt, opp_pt = contest.get("redPoint"), contest.get("bluePoint")
    else:
        my_pt, opp_pt = contest.get("bluePoint"), contest.get("redPoint")
    cards = contest.get("cards") or {}
    return {
        "contestId": cid,
        "type": contest.get("contestType"),
        "ri": contest.get("roundIndex"),
        "myPt": my_pt, "oppPt": opp_pt,
        "myCard": cards.get(my_color),
        "oppCard": cards.get(opp_color),
    }


def reject_fields_list(world, player_id):
    """本方上一帧被拒动作列表（每项 {round, action, target, code}）。"""
    out = []
    if world is None:
        return out
    for r in world.action_results:
        if r.get("playerId") == player_id and r.get("accepted") is False:
            out.append({
                "round": r.get("round"),
                "action": r.get("action"),
                "target": r.get("targetNodeId"),
                "code": r.get("errorCode"),
            })
    return out


def budget_fields(rnd, est, duration_round):
    """Budget 行字段；est 为 None/inf 时返回 None（跳过该事件）。"""
    if est is None:
        return None
    try:
        if est == float("inf"):
            return None
    except TypeError:
        return None
    return {"round": rnd, "est": int(est),
            "left": (duration_round or 600) - (rnd or 0)}


def start_extra_fields(ctx):
    """Start 行补充地图角色：gate/terminals/processNodes（一次性，供分析重建骨架）。

    只包含非空字段，无地图时返回 {}。
    """
    gm = ctx.game_map
    if gm is None:
        return {}
    out = {}
    if gm.gate_node:
        out["gate"] = gm.gate_node
    if gm.terminal_nodes:
        out["terminals"] = gm.terminal_nodes
    if gm.process_nodes:
        out["processNodes"] = sorted(gm.process_nodes.keys())
    return out


def run_loop(client, engine, logger, match_id, player_id):
    """主帧循环：处理 inquire / over / error。"""
    log_state = {"prev_blocks": {}}  # 跨帧阻塞快照（Block 事件变化触发用）
    while True:
        msg = client.recv(config.RECV_LOOP_TIMEOUT)
        if msg is None:
            if client.recv_ended.is_set():
                logger.trace("Error", error="disconnected",
                             detail=str(client.error) if client.error else None)
                return
            continue  # 超时，服务端尚未下发，继续等待

        name = messages.msg_name(msg)
        data = messages.msg_data(msg)

        if name == MsgName.INQUIRE:
            _handle_inquire(client, engine, logger, match_id, player_id, data, log_state)
        elif name == MsgName.OVER:
            _log_over(logger, player_id, data)
            return
        elif name == MsgName.ERROR:
            _log_error(logger, None, data)
        else:
            logger.trace("Recv", msg=name, note="unexpected_in_loop")


def _handle_inquire(client, engine, logger, match_id, player_id, data, log_state):
    rnd = data.get("round")

    world = None
    try:
        world = WorldState(data, player_id, engine.ctx.game_map)
    except Exception as exc:  # 解析异常
        logger.trace("Error", round=rnd, error="parse_exception", detail=repr(exc))
    _log_frame(logger, rnd, data, world)
    _log_blocks(logger, rnd, world, log_state)
    _log_contests(logger, world, player_id)
    _log_rejects(logger, world, player_id)

    t0 = time.perf_counter()
    actions = []
    if world is not None:
        try:
            actions = engine.decide(world)
        except Exception as exc:  # 决策异常绝不能拖垮心跳
            logger.trace("Error", round=rnd, error="decide_exception", detail=repr(exc))
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    try:
        client.send(messages.build_action(match_id, rnd, player_id, actions))
    except OSError as exc:
        logger.trace("Error", round=rnd, error="send_failed", detail=str(exc))
        return

    _log_budget(logger, rnd, engine.last_deliver_estimate, engine.ctx.duration_round)
    _log_actions(logger, rnd, actions, elapsed_ms)


def _log_actions(logger, rnd, actions, elapsed_ms):
    """每个动作写一行 Action trace；空动作（系统等待/心跳）也显式记录一行。"""
    over_budget = elapsed_ms > config.DECISION_BUDGET * 1000
    ms = elapsed_ms if over_budget else None  # 只在超预算时附带耗时，保持精简
    if not actions:
        logger.trace("Action", round=rnd, action="NONE", note="heartbeat", ms=ms)
        return
    for action in actions:
        logger.trace("Action", round=rnd, ms=ms, **_action_fields(action))
        ms = None  # 耗时只标在本帧首行


def _log_frame(logger, rnd, data, world):
    """记录每帧关键状态（本方+对手镜像+天气）与事件类型，供赛后分析。"""
    logger.trace("Frame", **frame_fields(rnd, data, world))


def _log_blocks(logger, rnd, world, log_state):
    """阻塞快照按变化触发：新增/变化记 Block，解除记 Block cleared。"""
    changed, cleared, cur = block_diff(world, log_state.get("prev_blocks", {}))
    log_state["prev_blocks"] = cur
    for nid, sig in changed:
        obstacle, owner, gdef = sig
        logger.trace("Block", round=rnd, node=nid,
                     obstacle=obstacle, guardOwner=owner, guardDef=gdef)
    for nid in cleared:
        logger.trace("Block", round=rnd, node=nid, cleared=True)


def _log_contests(logger, world, player_id):
    """本方参与窗口的每拍快照（同帧多窗口各写一行）。"""
    if world is None:
        return
    for c in world.my_contests():
        f = contest_fields(world, c, player_id)
        logger.trace("Contest", **f)


def _log_rejects(logger, world, player_id):
    """本方上一帧被拒动作（每条一行）。"""
    for f in reject_fields_list(world, player_id):
        logger.trace("Reject", **f)


def _log_budget(logger, rnd, est, duration_round):
    """交付预算估值（分析预算漂移）；est 不可用时跳过。"""
    f = budget_fields(rnd, est, duration_round)
    if f is not None:
        logger.trace("Budget", **f)


def main(argv):
    player_id, host, port = parse_args(argv)
    logger = MatchLogger(resolve_log_dir(), player_id)
    logger.trace("Startup", playerId=player_id, host=host, port=port,
                 version=config.CLIENT_VERSION)

    client = TcpClient(host, port, logger)
    try:
        client.connect(config.CONNECT_TIMEOUT)
    except OSError as exc:
        logger.trace("Error", error="connect_failed", detail=str(exc))
        logger.close()
        return 1

    try:
        # 1) registration
        client.send(messages.build_registration(
            player_id, config.DEFAULT_PLAYER_NAME, config.CLIENT_VERSION))
        logger.trace("Register", playerId=player_id, name=config.DEFAULT_PLAYER_NAME)

        # 2) start
        start = wait_for(client, MsgName.START, config.HANDSHAKE_TIMEOUT, logger)
        if start is None:
            logger.trace("Error", error="no_start_received")
            return 1
        sdata = messages.msg_data(start)
        match_id = sdata.get("matchId")
        logger.bind_match(match_id or "unknown")
        team_id, camp = messages.find_self_player(sdata, player_id)

        # 3) ready（round 用 start.round，通常为 1）
        ready_round = sdata.get("round") or 1
        client.send(messages.build_ready(match_id, ready_round, player_id))
        logger.trace("Ready", round=ready_round)

        # 4) 主循环
        ctx = GameContext(player_id, team_id, camp, sdata)
        engine = DecisionEngine(ctx)
        logger.trace("Start", teamId=team_id, camp=camp,
                     durationRound=sdata.get("durationRound"),
                     nodes=len(sdata.get("nodes", []) or []),
                     edges=len(sdata.get("edges", []) or []),
                     **start_extra_fields(ctx))
        run_loop(client, engine, logger, match_id, player_id)
        return 0
    finally:
        client.close()
        logger.trace("Shutdown")
        logger.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
