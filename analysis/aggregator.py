"""跨局聚合器：多份单局 `Report` → `analysis_report.md` / `ab_report.md`。

见 `docs/iteration_plan_v2.md` §3.3。**只抽取事实、不做优化、不出建议**：跨局统计 +
场景分段 + 运气分类 + 异常局标记 + seed 配对 A/B + `core/rules.py` 对账自检。

输入是 `parser.parse_log` 产出的 Report dict 列表（schemaVersion=1）。AI 读本模块产出的
聚合报告做归因，不直读 10w 字 trace。
"""

import math
import os
import statistics

try:
    from core import rules  # 对账自检复用规则镜像（client.core）
except Exception:  # pragma: no cover - 仅在 path 未配置时
    rules = None

SUPPORTED_SCHEMA = 1
AB_MIN_SAMPLE = 30
RARE_EVENT_MIN_SAMPLE = 100
RECON_TOLERANCE = 1.5


# ---------------------------------------------------------------------------
# 统计辅助
# ---------------------------------------------------------------------------

def _nums(reports, fn):
    return [v for v in (fn(r) for r in reports) if v is not None]


def _rate(reports, pred):
    if not reports:
        return 0.0
    return sum(1 for r in reports if pred(r)) / len(reports)


def _dist(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return {"n": len(vals), "min": vals[0], "median": statistics.median(vals),
            "mean": statistics.mean(vals), "max": vals[-1]}


def _fmt_dist(d, key):
    if not d:
        return "%s: n=0" % key
    return ("%s: n=%d, min=%.0f, median=%.0f, mean=%.1f, max=%.0f"
            % (key, d["n"], d["min"], d["median"], d["mean"], d["max"]))


def _ci95(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    mean = statistics.mean(values)
    if len(values) < 2:
        return (mean, float("inf"))
    sd = statistics.stdev(values)
    return (mean, 1.96 * sd / math.sqrt(len(values)))


def _fmt_ci(ci):
    if not ci:
        return "n/a"
    mean, hw = ci
    if math.isinf(hw):
        return "n/a (low N)"
    return "[%.1f, %.1f]" % (mean - hw, mean + hw)


# ---------------------------------------------------------------------------
# 对账自检（§3.6）：用 rules.py 从 report 原始输入重算终局分，与报告 total 比对
# ---------------------------------------------------------------------------

def recompute_total(report):
    """返回 (total, components, ok)。缺原始输入时 ok=False。"""
    if rules is None:
        return None, None, False
    final = (report.get("finalScore") or {}).get("me") or {}
    me_task = ((report.get("tasks") or {}).get("me") or {}).get("base") or 0
    delivery = (report.get("delivery") or {}).get("me") or {}
    good = delivery.get("goodFruit")
    fresh = delivery.get("freshness")
    deliver_frame = delivery.get("frame")
    traj = (report.get("trajectory") or {}).get("freshness") or {}
    if fresh is None:
        fresh = traj.get("end")
    if good is None:
        good = ((report.get("trajectory") or {}).get("goodFruit") or {}).get("end")
    if deliver_frame is None or good is None or fresh is None:
        return None, None, False
    delivered = bool(deliver_frame) and deliver_frame > 0
    bounty = final.get("bounty") or 0
    penalty = final.get("penalty") or 0
    if delivered:
        comps = {
            "delivery": rules.delivery_base_score(me_task),
            "goodFruit": rules.good_fruit_score(good),
            "freshness": rules.freshness_score(fresh),
            "time": rules.time_score(deliver_frame, me_task),
            "task": rules.task_score(me_task, delivered=True),
            "bounty": bounty,
        }
    else:
        comps = {"task": rules.task_score(me_task, delivered=False),
                 "bounty": rules.bounty_score(0, delivered=False)}
    total = max(0, sum(comps.values()) - penalty)
    return total, comps, True


def reconcile(report):
    """返回 (ok, error, note)。reported total>0 才对账；否则标 stub。"""
    final = (report.get("finalScore") or {}).get("me") or {}
    reported = final.get("total") or 0
    if not reported:
        return None, None, "no_real_score"
    total, _comps, ok = recompute_total(report)
    if not ok:
        return None, None, "missing_inputs"
    err = total - reported
    return (abs(err) <= RECON_TOLERANCE), err, None


# ---------------------------------------------------------------------------
# 字段访问
# ---------------------------------------------------------------------------

def _me_total(r):
    return ((r.get("finalScore") or {}).get("me") or {}).get("total") or None


def _me_deliver_frame(r):
    return ((r.get("delivery") or {}).get("me") or {}).get("frame") or None


def _me_task_base(r):
    return ((r.get("tasks") or {}).get("me") or {}).get("base") or None


def _proj_error(r):
    return (r.get("projection") or {}).get("error")


def _segments_of(r):
    return (r.get("classification") or {}).get("segments", [])


# ---------------------------------------------------------------------------
# 场景分段（§3.7）
# ---------------------------------------------------------------------------

SEGMENT_NAMES = ["delivered", "undelivered", "task90_reached", "task90_missed",
                 "mid_lead", "mid_trail", "mid_even", "weather_hit",
                 "contested", "opp_delivered", "opp_undelivered"]


def segment_block(reports):
    lines = []
    for name in SEGMENT_NAMES:
        sub = [r for r in reports if name in _segments_of(r)]
        if not sub:
            continue
        win = _rate(sub, lambda r: r.get("outcome") == "WIN")
        scores = _nums(sub, _me_total)
        mean = statistics.mean(scores) if scores else 0.0
        stuck = sum(len(((r.get("failures") or {}).get("waitingStuck") or [])) for r in sub)
        lines.append("  %-18s (N=%d): W %.2f, mean %.0f, stuck %d"
                     % (name, len(sub), win, mean, stuck))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 异常局标记（§3.3 / §3.8，仅作假设来源）
# ---------------------------------------------------------------------------

def flag_anomalies(reports):
    flagged = []
    for r in reports:
        reasons = []
        outcome = r.get("outcome")
        cls = (r.get("classification") or {}).get("luckClass")
        stuck = ((r.get("failures") or {}).get("waitingStuck") or [])
        proj_err = _proj_error(r)
        if outcome == "UNDELIVERED":
            reasons.append("UNDELIVERED")
        if stuck:
            reasons.append("waitingStuck=%d" % len(stuck))
        if proj_err is not None and abs(proj_err) > 50:
            reasons.append("projError=%s" % proj_err)
        if cls == "unlucky_loss":
            reasons.append("unlucky_loss")
        if cls == "lucky_win":
            reasons.append("lucky_win")
        if outcome == "LOSS" and "task90_missed" in _segments_of(r):
            ms = ((r.get("tasks") or {}).get("me") or {}).get("base", 0)
            reasons.append("loss+task<90(base=%s)" % ms)
        if reasons:
            flagged.append((r, reasons))
    return flagged


def luck_tally(reports):
    tally = {}
    for r in reports:
        cls = (r.get("classification") or {}).get("luckClass") or "unknown"
        tally[cls] = tally.get(cls, 0) + 1
    return tally


def failure_freq(reports):
    out = {"rejected": 0, "waitingStuck": 0, "invalidActions": 0,
           "decisionTimeouts": 0, "canAffordBlocked": 0}
    for r in reports:
        f = r.get("failures") or {}
        out["rejected"] += len(f.get("rejected") or [])
        out["waitingStuck"] += len(f.get("waitingStuck") or [])
        out["invalidActions"] += f.get("invalidActions") or 0
        out["decisionTimeouts"] += f.get("decisionTimeouts") or 0
        out["canAffordBlocked"] += len(f.get("canAffordBlocked") or [])
    return out


def mode_switch_freq(reports):
    return sum(len((r.get("projection") or {}).get("modeSwitches") or []) for r in reports)


# ---------------------------------------------------------------------------
# 索引（index.json）：matchId → outcome/score/luckClass/segments/reportPath
# ---------------------------------------------------------------------------

def build_index(reports, report_relpath=None):
    """供 AI 快速定位单局：按 outcome/luckClass/segments 过滤后下钻 report.json。

    report_relpath(matchId) -> 相对路径字符串；None 则不附 reportPath。
    """
    out = []
    for r in reports:
        mid = r.get("matchId")
        entry = {
            "matchId": mid,
            "source": r.get("source") or "unknown",
            "variant": r.get("variant") or "baseline",
            "clientVersion": r.get("clientVersion"),
            "seed": r.get("seed"),
            "outcome": r.get("outcome"),
            "score": _me_total(r),
            "luckClass": (r.get("classification") or {}).get("luckClass"),
            "segments": _segments_of(r),
            "deliverFrame": _me_deliver_frame(r),
            "taskBase": _me_task_base(r),
        }
        if report_relpath is not None and mid is not None:
            entry["reportPath"] = report_relpath(mid)
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# 异常局时序摘要（timelines.md）：关键事件链，跨局看典型输赢模式
# ---------------------------------------------------------------------------

# timeline 事件渲染优先级（关键动作用更醒目的标记）
_TL_MARK = {
    "MODE_CHANGE": "MODE", "RUSH_TACTIC": "RUSH", "TASK_CLAIM": "TASK",
    "BREAKTHROUGH": "BREAK", "SET_GUARD": "GUARD", "WINDOW_CARD": "WIND",
    "REJECTED": "REJ", "USE_ICE": "ICE", "USE_HORSE": "HORSE", "BOUNTY": "BNTY",
}


def _timeline_line(report):
    tl = (report.get("decisionTimeline") or [])
    parts = []
    for t in tl:
        mark = _TL_MARK.get(t.get("event"), t.get("event"))
        parts.append("r%s %s %s" % (t.get("frame"), mark, t.get("detail") or ""))
    return " | ".join(parts)


def build_timelines(reports, max_per_match=80):
    """对异常局输出关键事件链 → timelines.md。仅异常局（假设来源），全语料验证后才动手。"""
    flagged = flag_anomalies(reports)
    if not flagged:
        return None
    L = ["# Anomaly Timelines — cumulative N=%d anomaly games" % len(flagged), "",
         "> 仅异常局（UNDELIVERED / waitingStuck / projError>50 / unlucky_loss / lucky_win / loss+task<90）。",
         "> 单局只作假设来源，决策须基于全语料聚合 + CI + 分段不回归（§3.3/§3.8）。", ""]
    for r, reasons in flagged:
        mid = r.get("matchId")
        segs = ",".join(_segments_of(r)) or "-"
        cls = (r.get("classification") or {}).get("luckClass") or "-"
        score = _me_total(r)
        L.append("## matchId=%s  outcome=%s  luck=%s  score=%s  segments=%s"
                 % (mid, r.get("outcome"), cls, score if score is not None else "-", segs))
        L.append("  flags: %s" % "; ".join(reasons))
        line = _timeline_line(r)
        if not line:
            L.append("  (无 timeline 事件)")
        elif len(line) > max_per_match * 60:
            L.append("  " + line[:max_per_match * 60] + " ... (truncated)")
        else:
            L.append("  " + line)
        L.append("")
    return "\n".join(L)


def me_score_components(reports):
    """各分项分均值（用 rules.py 从原始输入重算；trace 不直接携带分项分）。"""
    keys = ("delivery", "task", "time", "goodFruit", "freshness", "bounty")
    out = {k: 0.0 for k in keys}
    n = 0
    for r in reports:
        _total, comps, ok = recompute_total(r)
        if not ok or not comps:
            continue
        n += 1
        for k in keys:
            out[k] += comps.get(k, 0) or 0
    if n:
        for k in keys:
            out[k] = round(out[k] / n, 1)
    return out


# ---------------------------------------------------------------------------
# A/B 配对
# ---------------------------------------------------------------------------

def _outcome_rank(r):
    o = r.get("outcome")
    return {"WIN": 3, "TIE": 2, "LOSS": 1, "UNDELIVERED": 0, "RETIRED": 0}.get(o, 0)


def ab_pair(reports):
    """按 seed 配对 variant vs baseline。返回 (baseline_name, variant_name, pairs) 或 None。"""
    by_seed_var = {}
    for r in reports:
        seed = r.get("seed")
        if seed is None:
            continue
        var = r.get("variant") or "baseline"
        by_seed_var.setdefault((seed, var), []).append(r)
    variants = sorted({v for (_s, v) in by_seed_var})
    if len(variants) < 2:
        return None
    baseline_name = "baseline" if "baseline" in variants else variants[0]
    variant_name = next((v for v in variants if v != baseline_name), None)
    if not variant_name:
        return None
    pairs = []
    for (seed, var) in by_seed_var:
        if var != baseline_name:
            continue
        for b in by_seed_var[(seed, baseline_name)]:
            for v in by_seed_var.get((seed, variant_name), []):
                pairs.append((b, v, seed))
    return baseline_name, variant_name, pairs


def ab_report(reports):
    paired = ab_pair(reports)
    if not paired:
        return None
    baseline_name, variant_name, pairs = paired
    b_wins = sum(1 for b, v, _ in pairs if _outcome_rank(v) > _outcome_rank(b))
    v_wins = sum(1 for b, v, _ in pairs if _outcome_rank(v) < _outcome_rank(b))
    ties = len(pairs) - b_wins - v_wins
    b_scores = [_me_total(b) for b, v, _ in pairs if _me_total(b) is not None]
    v_scores = [_me_total(v) for b, v, _ in pairs if _me_total(v) is not None]
    diffs = [(_me_total(v) or 0) - (_me_total(b) or 0) for b, v, _ in pairs]
    mean_diff = statistics.mean(diffs) if diffs else 0.0
    ci = _ci95(diffs)
    low_sample = len(pairs) < AB_MIN_SAMPLE
    b_deliver = _rate([b for b, v, _ in pairs],
                      lambda r: r.get("outcome") in ("WIN", "LOSS", "TIE"))
    v_deliver = _rate([v for b, v, _ in pairs],
                      lambda r: r.get("outcome") in ("WIN", "LOSS", "TIE"))

    seg_reg = []
    for name in SEGMENT_NAMES:
        bseg = [b for b, v, _ in pairs if name in _segments_of(b)]
        vseg = [v for b, v, _ in pairs if name in _segments_of(v)]
        if not bseg or not vseg:
            continue
        bm = statistics.mean([_me_total(b) for b in bseg if _me_total(b) is not None] or [0])
        vm = statistics.mean([_me_total(v) for v in vseg if _me_total(v) is not None] or [0])
        if vm < bm - 5:
            seg_reg.append("  %s 段 mean: %s %.0f / %s %.0f (%.0f)  ⚠ 成功路径劣化"
                           % (name, baseline_name, bm, variant_name, vm, vm - bm))

    def _reach(name):
        sub = [r for r in reports if (r.get("variant") or "baseline") == name]
        if not sub:
            return 0.0
        return _rate(sub, lambda r: "task90_reached" in _segments_of(r))

    lines = ["# A/B Paired — %s vs %s" % (baseline_name, variant_name), ""]
    lines.append(("SAMPLE NOTE: N=%d < %d，结论标'假设级'，不合入（§3.7）" % (len(pairs), AB_MIN_SAMPLE)
                  if low_sample else "SAMPLE NOTE: N=%d 达 A/B 门槛" % len(pairs)))
    lines += ["",
              "PAIRED:        %s wins %d / %s wins %d / ties %d (N=%d)"
              % (baseline_name, b_wins, variant_name, v_wins, ties, len(pairs)),
              "MEAN_SCORE:    %s %.0f / %s %.0f (diff %+.1f, 95%% CI %s)"
              % (baseline_name, statistics.mean(b_scores) if b_scores else 0,
                 variant_name, statistics.mean(v_scores) if v_scores else 0,
                 mean_diff, _fmt_ci(ci)),
              "DELIVERY_RATE: %s %.2f / %s %.2f" % (baseline_name, b_deliver, variant_name, v_deliver),
              "TASK_90_REACH: %s %.2f / %s %.2f"
              % (baseline_name, _reach(baseline_name), variant_name, _reach(variant_name))]
    if seg_reg:
        lines += ["", "SEGMENT REGRESSION（任一回归即不合入，§3.8）:"] + seg_reg
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主报告
# ---------------------------------------------------------------------------

def build_analysis_report(reports):
    n = len(reports)
    delivered = [r for r in reports if r.get("outcome") in ("WIN", "LOSS", "TIE")]
    wins = [r for r in reports if r.get("outcome") == "WIN"]
    score_vals = _nums(reports, _me_total)
    score_vals_nonzero = [v for v in score_vals if v and v > 0]
    frame_vals = _nums(reports, _me_deliver_frame)
    task_vals = _nums(reports, _me_task_base)
    proj_errs = _nums(reports, _proj_error)

    recon_ok = recon_bad = recon_stub = 0
    recon_errors = []
    for r in reports:
        ok, err, note = reconcile(r)
        if note == "no_real_score":
            recon_stub += 1
        elif ok is True:
            recon_ok += 1
        elif ok is False:
            recon_bad += 1
            recon_errors.append((r.get("matchId"), err))
        else:
            recon_stub += 1

    luck = luck_tally(reports)
    fail = failure_freq(reports)

    L = ["# Aggregated Report — cumulative N=%d games" % n,
         "source=%s variant=%s" % (",".join(sorted({r.get("source") or "unknown" for r in reports})),
                                   ",".join(sorted({r.get("variant") or "baseline" for r in reports})))]
    if n < AB_MIN_SAMPLE:
        L.append("SAMPLE NOTE: N=%d < %d，整体结论标'假设级'（§3.7）" % (n, AB_MIN_SAMPLE))
    L += ["",
          "## 总体",
          "WIN_RATE:       %.2f (%d/%d)" % (_rate(reports, lambda r: r.get("outcome") == "WIN"), len(wins), n),
          "DELIVERY_RATE:  %.2f (%d/%d)" % (_rate(reports, lambda r: r.get("outcome") in ("WIN", "LOSS", "TIE")), len(delivered), n),
          "MEAN_SCORE:     %.1f (n_with_real_score=%d)" % (statistics.mean(score_vals_nonzero) if score_vals_nonzero else 0.0, len(score_vals_nonzero)),
          "DELIVERY_FRAME: %s" % _fmt_dist(_dist(frame_vals), "frame"),
          "TASK_BASE:      %s" % _fmt_dist(_dist(task_vals), "task_base"),
          "TASK_90_REACH:  %.2f" % _rate(reports, lambda r: "task90_reached" in _segments_of(r)),
          "PROJ_ERROR:     %s" % _fmt_dist(_dist(proj_errs), "proj_err"),
          "MODE_SWITCHES:  %d total (%.2f/game)" % (mode_switch_freq(reports), mode_switch_freq(reports) / n if n else 0.0),
          "",
          "## 分项分均值（me，rules.py 从原始输入重算）",
          "  " + ", ".join("%s=%.1f" % (k, v) for k, v in me_score_components(reports).items()),
          "",
          "## 失败模式频次",
          "  " + ", ".join("%s=%d" % (k, v) for k, v in fail.items())]
    if n and n < RARE_EVENT_MIN_SAMPLE:
        L.append("  (N<%d，罕见事件频率仅作假设，§3.7)" % RARE_EVENT_MIN_SAMPLE)
    L += ["",
          "## 运气分类（luck class，§3.8）",
          "  " + ", ".join("%s=%d" % (k, v) for k, v in sorted(luck.items())),
          "  → unlucky_loss 为修 bug 首选；lucky_win 勿当实力强化",
          "",
          "## 场景分段（防单点劣化的主防线，§3.7）",
          segment_block(reports) or "  (无分段数据)",
          "",
          "## 对账自检（rules.py 重算 vs 报告 total，§3.6）",
          "  ok=%d, mismatch=%d, stub/missing=%d" % (recon_ok, recon_bad, recon_stub)]
    if recon_errors:
        L.append("  MISMATCH 详情（规则镜像可能与平台不符，须核查）:")
        for mid, err in recon_errors[:20]:
            L.append("    - matchId=%s error=%+.1f" % (mid, err))
    L += ["",
          "## 异常局标记（仅假设来源，须全语料验证后才动手，§3.3/§3.8）"]
    flagged = flag_anomalies(reports)
    if flagged:
        for r, reasons in flagged[:30]:
            L.append("  - matchId=%s outcome=%s → %s"
                     % (r.get("matchId"), r.get("outcome"), "; ".join(reasons)))
    else:
        L.append("  (无)")
    return "\n".join(L) + "\n"
