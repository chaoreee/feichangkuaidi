"""决策引擎。

M1 占位实现：每帧只返回空动作 `[]`（有效心跳），不主动做任何操作——
用于打通通信闭环、验证全程不因缺动作退赛。
移动/处理/验核等状态由服务端按规则推进。

M3 起在 decide() 中实现真正策略：输入 inquire 数据（M2 后为 core.WorldState），
输出本帧合法 actions 列表。策略始终与通信解耦，不 import socket。
"""


class GameContext:
    """跨帧静态/半静态上下文（开局缓存）。M2 起承载地图与规则镜像。"""

    def __init__(self, player_id, team_id=None, camp=None, start_data=None):
        self.player_id = int(player_id)
        self.team_id = team_id
        self.camp = camp
        start_data = start_data or {}
        self.match_id = start_data.get("matchId")
        self.duration_round = start_data.get("durationRound")
        self.nodes = start_data.get("nodes", [])
        self.edges = start_data.get("edges", [])
        self.resources = start_data.get("resources", [])
        self.task_templates = start_data.get("taskTemplates", [])
        self.gameplay = (start_data.get("map", {}) or {}).get("gameplay", {})


class DecisionEngine:
    def __init__(self, context):
        self.ctx = context

    def decide(self, inquire_data):
        """返回本帧 actions 列表。M1 恒为空动作心跳。"""
        return []
