"""静态地图镜像 GameMap（由 start 消息构建）。

从 start.msg_data 的顶层 nodes[]/edges[] 构建；roles 优先读 map.gameplay.roles，
缺失时（如直接喂 map_config.json）按节点类型推断。提供：
- 相邻节点、边查询
- 到站移动量 move_amount（rules.to_station_move_amount）
- 最短路 shortest_path（按移动量或路线距离两种度量）
- 最短路线距离 route_distance（用于情报射程≤15、冲刺触发≤15 等距离口径）

方向规则（§2.3.3）：每条边从 fromNode→toNode 恒可达；bidirectional 时 toNode→fromNode 也可达。
bidirectional 缺省视为 True（map_config 无该字段；正式 start 会携带）。
"""

import math
from dataclasses import dataclass

from core import pathfind, rules


@dataclass
class Node:
    node_id: str
    name: str
    type: str
    x: int
    y: int
    is_start: bool = False
    is_terminal: bool = False


@dataclass
class Edge:
    edge_id: str
    from_node: str
    to_node: str
    route_type: str
    distance: int
    bidirectional: bool = True


class GameMap:
    def __init__(self, start_data):
        raw_nodes = start_data.get("nodes") or (start_data.get("map", {}) or {}).get("nodes") or []
        raw_edges = start_data.get("edges") or (start_data.get("map", {}) or {}).get("edges") or []

        self.nodes = {}
        for n in raw_nodes:
            node = Node(
                node_id=n.get("nodeId"),
                name=n.get("name"),
                type=n.get("type") or n.get("nodeType"),
                x=n.get("x"),
                y=n.get("y"),
                is_start=bool(n.get("start")) or (n.get("type") or n.get("nodeType")) == "START",
                is_terminal=bool(n.get("terminal")) or (n.get("type") or n.get("nodeType")) in ("FINISH", "TERMINAL"),
            )
            if node.node_id:
                self.nodes[node.node_id] = node

        self.edges = []
        # 邻接表：node -> [(neighbor, weight)]
        self._adj_move = {}
        self._adj_dist = {}
        for i, e in enumerate(raw_edges):
            frm = e.get("fromNodeId") or e.get("fromNode")
            to = e.get("toNodeId") or e.get("toNode")
            if not frm or not to:
                continue
            route_type = e.get("routeType")
            distance = e.get("distance", 0)
            bidir = e.get("bidirectional", True)
            edge = Edge(
                edge_id=e.get("edgeId") or ("E%02d" % (i + 1)),
                from_node=frm, to_node=to, route_type=route_type,
                distance=distance, bidirectional=bidir,
            )
            self.edges.append(edge)
            move_w = rules.to_station_move_amount(distance, route_type)
            self._add_adj(frm, to, move_w, distance)
            if bidir:
                self._add_adj(to, frm, move_w, distance)

        self.roles = self._parse_roles(start_data)
        self.process_nodes = self._parse_process_nodes(start_data)

    def _add_adj(self, a, b, move_w, dist_w):
        self._adj_move.setdefault(a, []).append((b, move_w))
        self._adj_dist.setdefault(a, []).append((b, dist_w))

    def _parse_roles(self, start_data):
        gameplay = (start_data.get("map", {}) or {}).get("gameplay", {}) or {}
        roles = dict(gameplay.get("roles") or {})
        # 缺失时按节点类型 / safeZones / reverifyNode 推断
        if not roles.get("startNodeId"):
            starts = [n.node_id for n in self.nodes.values() if n.is_start]
            if starts:
                roles["startNodeId"] = starts[0]
        if not roles.get("terminalNodeIds"):
            terms = [n.node_id for n in self.nodes.values() if n.is_terminal]
            if terms:
                roles["terminalNodeIds"] = terms
        if not roles.get("gateNodeId"):
            gates = [n.node_id for n in self.nodes.values() if n.type == "GATE"]
            if gates:
                roles["gateNodeId"] = gates[0]
            elif start_data.get("reverifyNode"):
                roles["gateNodeId"] = start_data["reverifyNode"].get("nodeId")
        if not roles.get("safeZoneNodeIds"):
            sz = [z.get("nodeId") for z in (start_data.get("safeZones") or [])]
            if sz:
                roles["safeZoneNodeIds"] = sz
        return roles

    def _parse_process_nodes(self, start_data):
        """固定处理站点集合 node_id -> {processType, processName, processRound}。

        优先 start.map.gameplay.processNodes（英文 processType）；再并入顶层 processNodes
        （map_config：中文 processName）。gate 也可能在其中，策略层单独用 VERIFY_GATE 处理。
        """
        result = {}
        gameplay = (start_data.get("map", {}) or {}).get("gameplay", {}) or {}
        for p in gameplay.get("processNodes", []) or []:
            nid = p.get("nodeId")
            if nid:
                result[nid] = {"processType": p.get("processType"),
                               "processRound": p.get("processRound", 0) or 0}
        for p in start_data.get("processNodes", []) or []:
            nid = p.get("nodeId")
            if nid and nid not in result:
                result[nid] = {"processType": p.get("processType"),
                               "processName": p.get("processName"),
                               "processRound": p.get("processRound", 0) or 0}
        return result

    # ---- 查询 ----

    @property
    def start_node(self):
        return self.roles.get("startNodeId")

    @property
    def gate_node(self):
        return self.roles.get("gateNodeId")

    @property
    def terminal_nodes(self):
        return self.roles.get("terminalNodeIds") or []

    def node(self, node_id):
        return self.nodes.get(node_id)

    def neighbors(self, node_id):
        """按静态边可达的相邻节点列表（不考虑运行期设卡/障碍）。"""
        return [nb for nb, _ in self._adj_move.get(node_id, ())]

    def edge_between(self, a, b):
        """返回从 a 出发、按方向可达 b 的边；无则 None。"""
        for e in self.edges:
            if e.from_node == a and e.to_node == b:
                return e
            if e.bidirectional and e.from_node == b and e.to_node == a:
                return e
        return None

    def move_amount(self, a, b):
        """相邻 a→b 的到站所需移动量；不相邻返回 inf。"""
        e = self.edge_between(a, b)
        if e is None:
            return math.inf
        return rules.to_station_move_amount(e.distance, e.route_type)

    def shortest_path(self, source, target, metric="move"):
        """最短路 (path, cost)。metric='move' 按到站移动量；'distance' 按路线距离。"""
        adj = self._adj_move if metric == "move" else self._adj_dist
        return pathfind.shortest_path(adj, source, target)

    def route_distance(self, source, target):
        """最短路线距离（累计边 distance 之和）；用于情报/冲刺等距离口径。不可达返回 inf。"""
        _, cost = self.shortest_path(source, target, metric="distance")
        return cost

    def distance_to_gate(self, source):
        return self.route_distance(source, self.gate_node) if self.gate_node else math.inf
