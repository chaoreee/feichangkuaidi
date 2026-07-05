"""Iter 36 §1.5 真实天气审计：大路 +20 杠杆在真实天气下是否缩水。

触发：`route_planner_eval` §1 用 `weather_coef=1.0`（上界乐观）算出大路净 +20。
但 compact.log 逐帧记了真实天气（HOT 1.5× / HEAVY_RAIN 1.3× 鲜度系数；HEAVY_RAIN+WATER
/ MOUNTAIN_FOG+MOUNTAIN 移动减速）。大路多 ~30 帧 → 多暴露天气，且大路 ROAD 不受移动减速
（山路 MOUNTAIN 受 MOUNTAIN_FOG 减速）。本审计从 67 局 compact.log 重构每局天气序列，
逐帧重跑马感知 walker（复用 `route_planner_eval.walk_route` 的 weather_seq 接入），得出
大路 vs 山路 Δ 在真实天气下的**分布**，对比 coef=1.0 的 +20 上界。

## 天气重构

compact.log `F rN w=TYPE` 行 = round N 起天气转为 TYPE（compact.py 在天气变化帧发 F 行，
rN 是真实变化 round）。重构：round 1..首事件前 = CLEAR（coef 1.0、移动 1000）；首事件后
按事件序列分段。天气全局（与路线无关），同一局的天气序列对山路/大路 walk 同样适用。

## 关注

- 大路 +30 帧落在哪段天气：若落在 HOT（1.5×）/HEAVY_RAIN（1.3×）→ 鲜度增益缩水；
  若落在 MOUNTAIN_FOG（1.0×）→ 不缩水。
- 山路 MOUNTAIN 边在 MOUNTAIN_FOG 下移动减速（1100）→ 山路多帧 → 大路相对更快（Δ 反增大）。
- 冰鉴 post-hoc 模型不变：天气降低 fresh_no_ice → 大路 2 冰鉴仍抵 2 crossing、山路 1 冰鉴抵 1。

## 输出

`reports/weather_audit.json`(<100KB) + `reports/weather_audit.md`。CLI：
`python3 -m analysis.route_weather_audit`。**纯观测，不合入策略改动。**
"""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT = os.path.join(_ROOT, "client")
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from analysis.sizeguard import fit_text  # noqa: E402
from analysis.route_planner_eval import (  # noqa: E402
    CANDIDATE_ROUTES, build_game_map, load_samples_start_data, walk_route,
)

_REPORTS = os.path.join(_ROOT, "reports")
_SAMPLES = os.path.join(_ROOT, "samples", "map_config.json")

# 天气鲜度系数（镜像 rules.FRESHNESS_WEATHER_COEF，仅供报告标注用）
_WCOEF = {"HOT": 1.5, "HEAVY_RAIN": 1.3, "MOUNTAIN_FOG": 1.0}


def parse_weather_sequence(text):
    """从 compact.log 文本提取天气变化序列 [(start_round, wtype), ...]。

    `F rN w=TYPE` 行：round N 起天气转 TYPE。同一 F 行可能含其他 token（n=/st=/...），
    只取 rN 与 w=。无天气事件的局返回 []（全程 CLEAR）。
    """
    seq = []
    for line in text.splitlines():
        if not line.startswith("F "):
            continue
        rnd = None
        wtype = None
        for tok in line.split()[1:]:
            if tok.startswith("r") and tok[1:].isdigit() and rnd is None:
                rnd = int(tok[1:])
            elif tok.startswith("w="):
                wtype = tok[2:]
        if rnd is not None and wtype is not None:
            seq.append((rnd, wtype))
    return seq


def _weather_summary(seq, max_round):
    """天气序列 → 覆盖 [1, max_round] 的天气分段（供报告标注天气压力）。

    交付帧之后的事件截断丢弃；每段 end = min(下个事件 start−1, max_round)。
    """
    if not seq:
        return {"phases": [(1, max_round, "CLEAR")],
                "clear_rounds": max_round, "bad_rounds": 0}
    phases = []
    prev_start = 1
    prev_type = "CLEAR"
    for start, wtype in seq:
        if start > max_round:
            break
        if start > prev_start:
            phases.append((prev_start, start - 1, prev_type))
        prev_start = start
        prev_type = wtype
    phases.append((prev_start, max_round, prev_type))
    bad = sum(b - a + 1 for a, b, t in phases if _WCOEF.get(t, 1.0) > 1.0)
    return {"phases": phases, "clear_rounds": max_round - bad, "bad_rounds": bad}


def _wtype_at(seq, frame_round):
    if not seq:
        return None
    wt = None
    for start, wtype in seq:
        if start <= frame_round:
            wt = wtype
        else:
            break
    return wt


def audit_game(gm, res_by_node, weather_seq):
    """对单局天气序列走山路 + 大路，返回双方投影 + Δ（真实天气 vs CLEAR）。

    delta_clear 复算（weather_seq=None）作对照上界；shrinkage = delta_real - delta_clear。
    """
    m = walk_route(gm, CANDIDATE_ROUTES["mountain"], res_by_node,
                   {"weather_seq": weather_seq})
    r = walk_route(gm, CANDIDATE_ROUTES["mainroad"], res_by_node,
                   {"weather_seq": weather_seq})
    if not m or not r:
        return None
    delta_real = {
        "score": round(r["score"] - m["score"], 2),
        "fresh": round(r["final_fresh"] - m["final_fresh"], 3),
        "good": r["final_good"] - m["final_good"],
        "deliver_frame": r["deliver_frame"] - m["deliver_frame"],
    }
    m_clear = walk_route(gm, CANDIDATE_ROUTES["mountain"], res_by_node, {})
    r_clear = walk_route(gm, CANDIDATE_ROUTES["mainroad"], res_by_node, {})
    delta_clear = round(r_clear["score"] - m_clear["score"], 2)

    # 大路额外帧窗口（mountain_deliver .. mainroad_deliver）落在哪种天气
    extra_wtypes = []
    for fr in range(m["deliver_frame"] + 1, r["deliver_frame"] + 1):
        wt = _wtype_at(weather_seq, fr)
        if wt and wt not in extra_wtypes:
            extra_wtypes.append(wt)

    return {
        "weather_seq": weather_seq,
        "mountain": {"score": m["score"], "fresh": m["final_fresh"],
                     "good": m["final_good"], "deliver_frame": m["deliver_frame"],
                     "ice": m["ice_inv"]},
        "mainroad": {"score": r["score"], "fresh": r["final_fresh"],
                     "good": r["final_good"], "deliver_frame": r["deliver_frame"],
                     "ice": r["ice_inv"]},
        "delta_real": delta_real,
        "delta_clear": delta_clear,
        "shrinkage": round(delta_real["score"] - delta_clear, 2),
        "extra_frame_weather": extra_wtypes,
    }


def audit_all(reports_dir=_REPORTS, samples_path=_SAMPLES):
    """遍历 reports/*.compact.log，逐局天气审计 + 聚合。"""
    start_data, res_by_node, _cfg = load_samples_start_data(samples_path)
    gm = build_game_map(start_data)
    files = sorted(f for f in os.listdir(reports_dir)
                   if f.endswith(".compact.log"))
    games = []
    for fn in files:
        with open(os.path.join(reports_dir, fn), encoding="utf-8") as fh:
            text = fh.read()
        seq = parse_weather_sequence(text)
        mid = fn.replace(".compact.log", "")
        res = audit_game(gm, res_by_node, seq)
        if res is None:
            continue
        res["matchId"] = mid
        res["weather_summary"] = _weather_summary(seq, res["mainroad"]["deliver_frame"])
        games.append(res)
    if not games:
        return None

    deltas = [g["delta_real"]["score"] for g in games]
    shrinks = [g["shrinkage"] for g in games]
    delta_clear = games[0]["delta_clear"]
    n = len(games)
    pos = sum(1 for d in deltas if d > 0.5)
    neg = sum(1 for d in deltas if d <= 0)
    mean = sum(deltas) / n
    var = sum((d - mean) ** 2 for d in deltas) / n
    std = var ** 0.5
    dmin, dmax = min(deltas), max(deltas)
    fresh_real = [g["delta_real"]["fresh"] for g in games]
    agg = {
        "n": n,
        "delta_clear": delta_clear,
        "delta_real_mean": round(mean, 2),
        "delta_real_std": round(std, 2),
        "delta_real_min": round(dmin, 2),
        "delta_real_max": round(dmax, 2),
        "delta_real_positive": pos,
        "delta_real_nonpositive": neg,
        "shrinkage_mean": round(sum(shrinks) / n, 2),
        "fresh_delta_mean": round(sum(fresh_real) / n, 3),
        "verdict": _verdict(mean, neg, delta_clear),
    }
    return {"aggregate": agg, "games": games}


def _verdict(mean, neg, delta_clear):
    if mean > 0.5 and neg == 0:
        return "稳住：真实天气下大路仍净正，且无单局反劣（+20 不缩水或缩水可忽略）"
    if mean > 0.5 and neg > 0:
        return "基本稳住但有个别反劣局：均值仍正，{} 局大路 ≤ 山路，须查天气压力".format(neg)
    if mean > 0:
        return "缩水但未反转：均值微正，杠杆减弱、§3 仍可验但预期收益下调"
    return "反转：真实天气下大路均值 ≤ 0，+20 杠杆不成立，§3 前须加天气感知门或放弃"


def _fmt_game(g):
    d = g["delta_real"]
    ws = g["weather_summary"]
    phases = " ".join("%s@r%d-%d" % (t, a, b) for a, b, t in ws["phases"])
    extra = "/".join(g["extra_frame_weather"]) or "CLEAR"
    return ("  %-44s Δreal=%+5.1f (clear %+4.1f, shrink %+5.1f) "
            "fresh=%+5.1f good=%+d extra_w=%s | %s" % (
                g["matchId"][:44], d["score"], g["delta_clear"], g["shrinkage"],
                d["fresh"], d["good"], extra, phases))


def build_report_md(audit):
    a = audit["aggregate"]
    games = audit["games"]
    lines = [
        "# Iter 36 §1.5 真实天气审计 — 大路 +20 在真实天气下是否缩水", "",
        "> 从 67 局 compact.log 重构逐帧天气序列（HOT 1.5× / HEAVY_RAIN 1.3× 鲜度系数；",
        "> MOUNTAIN_FOG+MOUNTAIN / HEAVY_RAIN+WATER 移动减速），重跑马感知 walker。",
        "> 对比 §1 的 coef=1.0 上界（大路净 +20）。**纯观测，不合入策略改动。**", "",
        "## 聚合（N=%d）" % a["n"], "",
        "- CLEAR 上界 Δ（无天气）：**%+.1f**" % a["delta_clear"],
        "- 真实天气 Δ 均值：**%+.2f**（std %.2f，min %+.2f / max %+.2f）" % (
            a["delta_real_mean"], a["delta_real_std"],
            a["delta_real_min"], a["delta_real_max"]),
        "- 缩水均值：**%+.2f**（负=天气缩水杠杆）" % a["shrinkage_mean"],
        "- 鲜度 Δ 均值：%+.3f" % a["fresh_delta_mean"],
        "- 大路净正局：%d/%d；大路 ≤ 山路局：%d" % (
            a["delta_real_positive"], a["n"], a["delta_real_nonpositive"]),
        "- 判定：**%s**" % a["verdict"],
        "",
        "## 逐局", "",
        "Δreal=真实天气大路−山路；clear=无天气上界；shrink=Δreal−clear（负=缩水）；",
        "extra_w=大路额外 ~30 帧落到的天气；phases=该局天气分段。", "",
    ]
    for g in games:
        lines.append(_fmt_game(g))
    lines.append("")
    lines.append("## 机制说明")
    lines.append("")
    lines.append("- 大路多 ~30 帧的天气暴露决定缩水：若额外帧落在 HOT(1.5×)/HEAVY_RAIN(1.3×) → "
                 "鲜度增益缩水；落在 MOUNTAIN_FOG(1.0×)/CLEAR(1.0×) → 不缩水。")
    lines.append("- 山路 MOUNTAIN 边在 MOUNTAIN_FOG 下移动减速（倍率 1100）→ 山路多帧 → "
                 "大路相对更快（Δ 反增）；大路 ROAD 不受任何天气移动减速。")
    lines.append("- 冰鉴 post-hoc 不变：天气降 fresh_no_ice，大路 2 冰鉴仍抵 2 crossing、"
                 "山路 1 冰鉴抵 1 → 好果 Δ 通常稳住。")
    lines.append("- 局限：compact.log 天气变化 round 取自 F 行（状态变化帧），若天气变化与状态变化"
                 "不同帧则有数帧延迟（<10%，可忽略）；walker 不建模障碍 CLEAR/任务领取帧的天气微差。")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Iter 36 real-weather route audit.")
    ap.add_argument("--reports", default=_REPORTS, help="reports dir (compact.logs)")
    ap.add_argument("--samples", default=_SAMPLES, help="map_config.json path")
    ap.add_argument("--out", default=os.path.join(_REPORTS, "weather_audit.json"))
    args = ap.parse_args(argv)

    audit = audit_all(args.reports, args.samples)
    if audit is None:
        print("no compact.log found in %s" % args.reports)
        return 1
    md = build_report_md(audit)
    payload = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True)
    if len(payload.encode("utf-8")) > 100_000:
        audit["games"] = [{k: v for k, v in g.items() if k != "weather_seq"}
                          for g in audit["games"]]
        payload = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(payload)
    print("wrote %s" % args.out)
    print(md)
    md_path = args.out.replace(".json", ".md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(fit_text(md + "\n"))
    print("wrote %s" % md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
