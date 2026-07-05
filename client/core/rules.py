"""规则公式镜像（纯函数，无副作用）。

集中实现任务书里可计算的规则，供 strategy 无副作用查询：
- 移动：到站所需移动量、每帧推进量、单边耗时估算（§2.3.2）
- 鲜度：每帧损耗、转坏阈值（§3.2）
- 天气：通行倍率、鲜度系数（§2.3.2 / §3.2.2）
- 设卡/强制通行：防守值、时间税（§6.2 / §6.3.2）
- 得分：送达/好果/鲜度/用时/任务里程碑/悬赏（§7.2 / §7.3）

数值口径严格对齐任务书；所有取整向下取整（floor），到站移动量向上取整（ceil）。
"""

import math


# ---- 路线（§2.3.2）----

# 路线耗时系数：每 1 点路线距离所需移动量
ROUTE_TIME_COEF = {"ROAD": 1380, "WATER": 1250, "MOUNTAIN": 1780, "BRANCH": 1550}
_ROUTE_COEF_FALLBACK = 1550  # 未知路线类型的保守回退（按支路）

# 每帧基础移动量
BASE_MOVE_NONE = 1000
BASE_MOVE = {"NONE": 1000, "FAST_HORSE": 1200, "SHORT_HORSE": 1150, "RUSH_SPEED": 1300}
HORSE_DURATION = {"FAST_HORSE": 20, "SHORT_HORSE": 14}
RUSH_SPEED_DURATION = 15
RUSH_PROTECT_DURATION = 30

# 天气通行倍率（命中时；未命中为 1000）
WEATHER_MOVE_MULT_RAIN_WATER = 1350   # 暴雨命中水路移动
WEATHER_MOVE_MULT_FOG_MOUNTAIN = 1100  # 山雾命中山路移动


def to_station_move_amount(distance, route_type):
    """到站所需移动量 = ceil(路线距离 × 路线耗时系数)。"""
    coef = ROUTE_TIME_COEF.get(route_type, _ROUTE_COEF_FALLBACK)
    return math.ceil(distance * coef)


def per_frame_move_amount(base_move=BASE_MOVE_NONE, weather_mult=1000):
    """每帧移动量 = floor(基础每帧移动量 × 1000 ÷ 当前天气通行倍率)。"""
    return (base_move * 1000) // weather_mult


def frames_on_edge(distance, route_type, base_move=BASE_MOVE_NONE, weather_mult=1000):
    """在一条边上到站所需的结算帧数估算（不考虑中途加速/天气变化）。"""
    amount = to_station_move_amount(distance, route_type)
    per = per_frame_move_amount(base_move, weather_mult)
    if per <= 0:
        return math.inf
    return math.ceil(amount / per)


def weather_move_multiplier(route_type, active_weather_type):
    """给定本帧生效天气类型，返回该路线类型移动的天气通行倍率。"""
    if active_weather_type == "HEAVY_RAIN" and route_type == "WATER":
        return WEATHER_MOVE_MULT_RAIN_WATER
    if active_weather_type == "MOUNTAIN_FOG" and route_type == "MOUNTAIN":
        return WEATHER_MOVE_MULT_FOG_MOUNTAIN
    return 1000


# ---- 鲜度（§3.2.2）----

FRESHNESS_LOSS_BASE = 0.05  # 停靠/等待/处理/验核/窗口/休整/强制通行额外等待
FRESHNESS_LOSS_MOVE = {"ROAD": 0.055, "WATER": 0.045, "MOUNTAIN": 0.07, "BRANCH": 0.065}
FRESHNESS_LOSS_MOVE_MIN = min(FRESHNESS_LOSS_MOVE.values())  # 水路 0.045，路由鲜度差分基准
_ROUTE_LOSS_FALLBACK = 0.065  # 未知路线类型按支路估算（保守）


def route_freshness_loss(route_type):
    """给定路线类型的每帧移动鲜度损耗（未知类型按支路回退）。"""
    return FRESHNESS_LOSS_MOVE.get(route_type, _ROUTE_LOSS_FALLBACK)

# 鲜度首次低于这些阈值时各触发 1 篓好果转坏（§3.2.1）
GOOD_TO_BAD_THRESHOLDS = (90, 80, 70, 60, 50, 40, 30, 20, 10)

# 天气鲜度系数（命中时）
FRESHNESS_WEATHER_COEF = {"HOT": 1.5, "HEAVY_RAIN": 1.3, "MOUNTAIN_FOG": 1.0}
# 急策鲜度系数
FRESHNESS_RUSH_COEF = {"RUSH_SPEED": 1.25, "RUSH_PROTECT": 0.2}


def freshness_loss(base_loss, weather_coef=1.0, rush_coef=1.0):
    """本帧鲜度扣除值 = 每帧基础鲜度扣除值 × 天气鲜度系数 × 急策鲜度系数。"""
    return base_loss * weather_coef * rush_coef


def crossed_good_to_bad_thresholds(before, after):
    """鲜度从 before 结算到 after 时，首次低于的阈值列表（各触发 1 次转坏）。

    等于阈值不触发；结算后严格低于才触发。仅统计 before 时尚未低于、after 时已低于的阈值。
    """
    return [t for t in GOOD_TO_BAD_THRESHOLDS if before >= t > after]


# ---- 设卡与强制通行（§6.2 / §6.3.2）----

OBSTACLE_TIME_TAX = 8  # 道路障碍时间税（固定）

# 设卡处理帧数（§6.2.1：设卡提交后处理 4 个结算帧才生成设卡）
SET_GUARD_PROCESS_FRAMES = 4

# 节点防守值上限（§6.2.1）：normal 6 / key_pass 7 / gate 4 / 已有障碍站点 5
NODE_MAX_DEFENSE = {"normal": 6, "key_pass": 7, "gate": 4, "obstacle_node": 5}


def guard_defense(extra_good_fruit, max_defense):
    """设卡防守值 = min(节点防守值上限, 2 + 额外投入好果 × 2)。"""
    return min(max_defense, 2 + extra_good_fruit * 2)


def guard_time_tax(node_kind, defense):
    """设卡强制通行时间税（§6.3.2）。node_kind ∈ normal/key_pass/gate/obstacle_node。"""
    if node_kind == "normal":
        return min(40, 10 + defense * 5)
    if node_kind == "key_pass":
        return min(50, 15 + defense * 5)
    if node_kind == "gate":
        return min(32, 12 + defense * 5)
    if node_kind == "obstacle_node":  # 已有道路障碍的站点设卡
        return min(28, 8 + defense * 5)
    return min(40, 10 + defense * 5)


def break_guard_attack_value(good_fruit=0, bad_fruit=0, break_order=False):
    """攻坚值 = 好果×2 + 坏果×3 + 破关令(+3)（§6.3.1）。"""
    return good_fruit * 2 + bad_fruit * 3 + (3 if break_order else 0)


# ---- 得分（§7.2 / §7.3）----

def delivery_base_score(task_base):
    """送达基础分 = min(240, 120 + floor(任务基础分累计 × 4 / 3))。需完成交付。"""
    return min(240, 120 + (task_base * 4) // 3)


def good_fruit_score(good_fruit):
    """好果数量分 = floor(交付时剩余好果 / 100 × 180)。"""
    return math.floor(good_fruit / 100 * 180)


def freshness_score(freshness):
    """鲜度品质分 = floor(交付时剩余鲜度 / 100 × 180)。"""
    return math.floor(freshness / 100 * 180)


def raw_time_score(deliver_round):
    """原始用时分 = floor((600 - 交付时间) / 600 × 70)。"""
    return math.floor((600 - deliver_round) / 600 * 70)


def time_score(deliver_round, task_base):
    """用时分 = floor(原始用时分 × min(任务基础分累计, 90) / 90)。"""
    return math.floor(raw_time_score(deliver_round) * min(task_base, 90) / 90)


def task_milestone_bonus(task_base):
    """任务里程碑奖励：<60→0，60-89→15，90-109→35，≥110→50。"""
    if task_base >= 110:
        return 50
    if task_base >= 90:
        return 35
    if task_base >= 60:
        return 15
    return 0


def task_score(task_base, delivered=True):
    """皇榜任务分。交付：min(180, 累计 + 里程碑)；未交付：min(累计, 80) 且无里程碑。"""
    if not delivered:
        return min(task_base, 80)
    return min(180, task_base + task_milestone_bonus(task_base))


def bounty_score(raw_bounty, delivered=True):
    """破关悬赏分。交付且原始>0：min(原始,80)+20；未交付：min(原始,25)；否则 0。"""
    if raw_bounty <= 0:
        return 0
    if not delivered:
        return min(raw_bounty, 25)
    return min(raw_bounty, 80) + 20


def total_score(components, penalty=0):
    """最终总分 = 所有正向分之和 − 惩罚，最低计 0（§7.3）。"""
    return max(0, sum(components) - penalty)
