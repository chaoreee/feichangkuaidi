"""客户端上行消息构造 + 下行消息访问助手（协议 §4/§6/§8）。

上行仅三类：registration / ready / action。下行为 dict，用 msg_name()/msg_data() 取值。
"""

from protocol.enums import MsgName


# ---------- 上行消息构造 ----------

def build_registration(player_id, player_name, version):
    return {
        "msg_name": MsgName.REGISTRATION,
        "msg_data": {
            "playerId": int(player_id),
            "playerName": player_name,
            "version": version,
        },
    }


def build_ready(match_id, round_no, player_id):
    return {
        "msg_name": MsgName.READY,
        "msg_data": {
            "matchId": match_id,
            "round": int(round_no),
            "playerId": int(player_id),
        },
    }


def build_action(match_id, round_no, player_id, actions):
    """构造 action 信封。actions 为空时发 [] 作为有效心跳（协议 §8）。"""
    return {
        "msg_name": MsgName.ACTION,
        "msg_data": {
            "matchId": match_id,
            "round": int(round_no),
            "playerId": int(player_id),
            "actions": list(actions) if actions else [],
        },
    }


# ---------- 下行消息访问 ----------

def msg_name(message):
    return message.get("msg_name") if isinstance(message, dict) else None


def msg_data(message):
    if isinstance(message, dict):
        data = message.get("msg_data")
        if isinstance(data, dict):
            return data
    return {}


def find_self_player(start_data, player_id):
    """从 start.players[] 里按 playerId 找到本方条目，返回 (teamId, camp) 或 (None, None)。"""
    pid = int(player_id)
    for p in start_data.get("players", []) or []:
        if int(p.get("playerId", -1)) == pid:
            return p.get("teamId"), p.get("camp")
    return None, None
