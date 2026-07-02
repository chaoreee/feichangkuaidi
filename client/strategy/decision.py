"""决策引擎。

M1/M2 占位实现：每帧只返回空动作 `[]`（有效心跳），不主动做任何操作——
用于打通通信闭环、验证全程不因缺动作退赛。移动/处理/验核等状态由服务端按规则推进。

M2 起 decide() 接收 core.WorldState（已解析的每帧公开状态，含地图/寻路/规则镜像）。
M3 起在此实现真正策略：输入 WorldState，输出本帧合法 actions 列表。策略始终与通信解耦，不 import socket。
"""

from core.game_map import GameMap


class GameContext:
    """跨帧静态/半静态上下文（开局缓存）。承载地图镜像 GameMap 与本方身份。"""

    def __init__(self, player_id, team_id=None, camp=None, start_data=None):
        self.player_id = int(player_id)
        self.team_id = team_id
        self.camp = camp
        start_data = start_data or {}
        self.match_id = start_data.get("matchId")
        self.duration_round = start_data.get("durationRound")
        self.task_templates = start_data.get("taskTemplates", [])
        try:
            self.game_map = GameMap(start_data)
        except Exception:
            self.game_map = None


class DecisionEngine:
    def __init__(self, context):
        self.ctx = context

    def decide(self, world):
        """返回本帧 actions 列表。world 为 core.WorldState。M2 恒为空动作心跳。"""
        return []
