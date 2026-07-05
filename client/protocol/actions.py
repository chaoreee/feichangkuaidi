"""动作对象构造器（协议 §8 动作字段矩阵 / 附录 E）。

每个函数返回一个 actions[] 数组里的单动作 dict。只填该动作相关字段，不带无关字段。
供 strategy 层组装本帧动作列表。
"""

from protocol.enums import Action


# ---- 主车队动作 ----

def wait():
    return {"action": Action.WAIT}


def move(target_node_id):
    return {"action": Action.MOVE, "targetNodeId": target_node_id}


def deliver():
    return {"action": Action.DELIVER}


def verify_gate(rush_tactic=None):
    a = {"action": Action.VERIFY_GATE}
    if rush_tactic:
        a["rushTactic"] = rush_tactic
    return a


def set_guard(target_node_id, extra_good_fruit=None):
    a = {"action": Action.SET_GUARD, "targetNodeId": target_node_id}
    if extra_good_fruit is not None:
        a["extraGoodFruit"] = int(extra_good_fruit)
    return a


def break_guard(target_node_id, good_fruit=None, bad_fruit=None, rush_tactic=None):
    a = {"action": Action.BREAK_GUARD, "targetNodeId": target_node_id}
    if good_fruit is not None:
        a["goodFruit"] = int(good_fruit)
    if bad_fruit is not None:
        a["badFruit"] = int(bad_fruit)
    if rush_tactic:
        a["rushTactic"] = rush_tactic
    return a


def forced_pass(target_node_id):
    return {"action": Action.FORCED_PASS, "targetNodeId": target_node_id}


def claim_resource(target_node_id, resource_type):
    return {
        "action": Action.CLAIM_RESOURCE,
        "targetNodeId": target_node_id,
        "resourceType": resource_type,
    }


def use_resource(resource_type, target_node_id=None):
    a = {"action": Action.USE_RESOURCE, "resourceType": resource_type}
    if target_node_id is not None:
        a["targetNodeId"] = target_node_id
    return a


def claim_task(task_id):
    return {"action": Action.CLAIM_TASK, "taskId": task_id}


def clear(target_node_id):
    return {"action": Action.CLEAR, "targetNodeId": target_node_id}


def process(target_node_id=None):
    a = {"action": Action.PROCESS}
    if target_node_id is not None:
        a["targetNodeId"] = target_node_id
    return a


def dock(target_node_id=None):
    a = {"action": Action.DOCK}
    if target_node_id is not None:
        a["targetNodeId"] = target_node_id
    return a


# ---- 小分队动作 ----

def squad_scout(target_node_id):
    return {"action": Action.SQUAD_SCOUT, "targetNodeId": target_node_id}


def squad_clear(target_node_id):
    return {"action": Action.SQUAD_CLEAR, "targetNodeId": target_node_id}


def squad_reinforce(target_node_id):
    return {"action": Action.SQUAD_REINFORCE, "targetNodeId": target_node_id}


def squad_weaken(target_node_id):
    return {"action": Action.SQUAD_WEAKEN, "targetNodeId": target_node_id}


# ---- 窗口出牌 ----

def window_card(contest_id, card, rush_tactic=None):
    a = {"action": Action.WINDOW_CARD, "contestId": contest_id, "card": card}
    if rush_tactic:
        a["rushTactic"] = rush_tactic
    return a


# ---- 终局急策 ----

def rush_speed():
    return {"action": Action.RUSH_SPEED}


def rush_protect():
    return {"action": Action.RUSH_PROTECT}
