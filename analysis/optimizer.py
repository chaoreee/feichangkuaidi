"""改进建议：将评估结论映射为策略/参数/Bug/架构改进建议。

返回 (area, issue, suggestion) 三元组列表，供 report 呈现并回写基线。
"""


def suggest(parsed, ev):
    out = []

    if not ev["delivered"]:
        out.append(("交付", "未完成交付",
                    "检查末帧状态(%s@%s)与时间预算：确认宫门验核后进入 S15，且交付时好果>0、鲜度>0；"
                    "若因遇阻卡住，检查突破/绕行逻辑" % (ev["last_state"], ev["last_node"])))

    if (ev["task_score"] or 0) < 90:
        out.append(("任务/得分", "皇榜任务累计<90",
                    "解锁满额送达基础分(240)与用时系数需累计≥90：提高机会式任务优先级，或为高价值任务适度绕路"))

    fresh = ev["final_freshness"]
    if fresh is not None and fresh < 60:
        out.append(("鲜度", "交付/末帧鲜度偏低",
                    "更早/更多使用冰鉴护住阈值，RUSH 用护果令，或选更快路线减少总耗时"))

    if ev["decision"]["over_budget"] > 0:
        out.append(("性能", "决策超时",
                    "缓存寻路结果、减少每帧重复计算，确保单帧决策<400ms"))

    if ev["exception_count"] > 0:
        details = [str(e.get("detail")) for e in parsed["errors"]
                   if str(e.get("error", "")).endswith("exception")]
        out.append(("Bug", "决策/解析异常",
                    "修复异常（前几条）：%s" % ("；".join(details[:3]) or "见日志")))

    dr, dur = ev["deliver_round"], parsed.get("duration_round")
    if ev["delivered"] and dr and dur and dr > dur * 0.85:
        out.append(("速度", "交付偏晚",
                    "用马/疾行令或更短路线提前交付以提高用时分"))

    other = ev["error_count"] - ev["exception_count"]
    if other > 0:
        out.append(("协议/规则", "存在错误或业务拒绝",
                    "核对 events/actionResults 错误码，修正发包或动作前置条件"))

    if not out:
        out.append(("维持", "无明显问题",
                    "表现良好；可继续提升任务分与更早交付以拉高总分，并加入对抗中的主动干扰"))
    return out
