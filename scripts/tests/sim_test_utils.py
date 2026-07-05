"""sim 测试共用工具：构造引擎 / start_data / 轻量动作提供器。"""

import json
import os

import _pathsetup  # noqa: F401
from core.game_map import GameMap
from sim_engine import SimEngine

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MAP = os.path.join(_ROOT, "samples", "map_config.json")


def load_mc():
    with open(_MAP, encoding="utf-8") as fh:
        return json.load(fh)


def build_start(seed=1, match_id="sim_test"):
    mc = load_mc()
    gp = mc.get("gameplay", {}) or {}
    grid = mc.get("grid", {}) or {}
    return {
        "matchId": match_id, "rulesVersion": "sim", "round": 1, "tick": 0,
        "durationRound": 600, "seed": seed,
        "map": {"maxX": grid.get("width", 80), "maxY": grid.get("height", 60),
                "gameplay": {"roles": gp.get("roles", {"startNodeId": "S01", "gateNodeId": "S14",
                                                       "terminalNodeIds": ["S15"], "safeZoneNodeIds": ["S15"]}),
                             "processNodes": gp.get("processNodes", [])}},
        "players": [{"playerId": 1001, "camp": 0, "teamId": "RED", "name": "sim-red"},
                    {"playerId": 2001, "camp": 1, "teamId": "BLUE", "name": "sim-blue"}],
        "nodes": mc["nodes"], "edges": mc["edges"],
        "resources": gp.get("resources", []),
        "taskTemplates": [{"taskTemplateId": "T01", "score": 30}],
    }, mc


def fresh_engine(seed=1):
    start, _ = build_start(seed=seed)
    gm = GameMap(start)
    eng = SimEngine(start, gm, seed=seed)
    return eng


def move_to(target):
    return {"action": "MOVE", "targetNodeId": target}
