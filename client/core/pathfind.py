"""Dijkstra 最短路（纯算法工具）。

图以邻接表表示：adjacency = { node: [(neighbor, weight), ...] }，weight 为非负数。
供 GameMap 计算按"到站移动量"或"路线距离"的最短路。
"""

import heapq
import math


def dijkstra(adjacency, source):
    """返回 (dist, prev)：dist[node]=源到该点最小累计权重；prev[node]=最短路前驱。"""
    dist = {source: 0}
    prev = {}
    pq = [(0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, math.inf):
            continue
        for v, w in adjacency.get(u, ()):  # noqa: E741
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def reconstruct_path(prev, source, target):
    """由 prev 回溯 source→target 的节点列表；不可达返回 None。"""
    if source == target:
        return [source]
    if target not in prev:
        return None
    path = [target]
    cur = target
    while cur != source:
        cur = prev.get(cur)
        if cur is None:
            return None
        path.append(cur)
    path.reverse()
    return path


def shortest_path(adjacency, source, target):
    """返回 (path, cost)；不可达返回 (None, inf)。"""
    dist, prev = dijkstra(adjacency, source)
    if target not in dist:
        return None, math.inf
    return reconstruct_path(prev, source, target), dist[target]
