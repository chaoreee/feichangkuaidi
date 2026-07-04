"""体积守卫：确保 `reports/` 下每个产物文件 < MAX_FILE_BYTES。

只对**写出时**的序列化产物做有损裁剪；喂给 aggregator 的内存 Report 保持全保真
（analysis_report.md / index / timelines 的聚合统计不受影响）。裁剪仅在**超预算时**
触发——小报告原样落盘，零风险。裁剪顺序：

1. **保信息合并**（count 合并连续相同条目，信息不丢）：
   - `failures.rejected` 连续相同 (action, code, target) → 一条带 `count`/`firstFrame`/`lastFrame`
   - `decisionTimeline` 连续相同 (event, detail) → 一条带 `count`/`lastFrame`
   - `failures.canAffordBlocked` 连续相同 (action, reason, target) → 一条带 `count`
2. **有损封顶**（保头尾 + 插 elision 标记，标注丢了多少）：逐级收紧 head/tail 上限。
3. **丢重字段**（`trajectory.opponent.frames`）+ **兜底**（timeline 置标）。

合并后的 rejected 条目带 `count` 字段；aggregator 的 `failure_freq`/`opp_guard_stats`
跑在内存全保真 Report 上（未被合并），故计数不受写盘裁剪影响。AI 若直接读 report.json
下钻，`count` 字段已保留总次数（如 vs2735 的 224 次 MOVE_BLOCKED_BY_GUARD → 1 条 count=224）。
"""

import copy
import json

MAX_FILE_BYTES = 100_000  # 硬上限：每个产物文件 <100KB


def _serialize(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def fit_report(report, max_bytes=MAX_FILE_BYTES):
    """返回一份可落盘的 Report（超预算时裁剪，否则原样返回不拷贝）。"""
    if len(_serialize(report)) <= max_bytes:
        return report
    r = copy.deepcopy(report)
    # Stage 1：保信息合并
    _coalesce_rejected(r)
    _coalesce_timeline(r)
    _coalesce_can_afford(r)
    if len(_serialize(r)) <= max_bytes:
        return r
    # Stage 2：逐级收紧封顶 (tl_head, tl_tail, rej_head, rej_tail, ca_head, ca_tail)
    caps = [(80, 80, 60, 60, 30, 30),
            (40, 40, 30, 30, 15, 15),
            (20, 20, 10, 10, 5, 5),
            (5, 5, 5, 5, 0, 0)]
    for tl_h, tl_t, rej_h, rej_t, ca_h, ca_t in caps:
        _cap_timeline(r, tl_h, tl_t)
        _cap_rejected(r, rej_h, rej_t)
        _cap_can_afford(r, ca_h, ca_t)
        if len(_serialize(r)) <= max_bytes:
            return r
    # Stage 3：丢重可选字段
    _drop_opp_frames(r)
    if len(_serialize(r)) <= max_bytes:
        return r
    # Stage 4：兜底——timeline 整体置标（保留 matchId/outcome/score 等标量字段）
    failures = r.get("failures") or {}
    if isinstance(failures.get("rejected"), list):
        failures["rejected"] = _elision_marker(len(failures["rejected"]), "rejected")
        r["failures"] = failures
    tl = r.get("decisionTimeline")
    if isinstance(tl, list):
        r["decisionTimeline"] = [_elision_marker(len(tl), "decisionTimeline")]
    return r


# ---------------------------------------------------------------------------
# Stage 1：保信息合并
# ---------------------------------------------------------------------------

def _coalesce_rejected(r):
    failures = r.get("failures") or {}
    entries = failures.get("rejected")
    if not isinstance(entries, list) or not entries:
        return
    failures["rejected"] = _coalesce_runs(entries, ("action", "code", "target"))
    r["failures"] = failures


def _coalesce_timeline(r):
    tl = r.get("decisionTimeline")
    if not isinstance(tl, list) or not tl:
        return
    r["decisionTimeline"] = _coalesce_runs(tl, ("event", "detail"))


def _coalesce_can_afford(r):
    failures = r.get("failures") or {}
    entries = failures.get("canAffordBlocked")
    if not isinstance(entries, list) or not entries:
        return
    failures["canAffordBlocked"] = _coalesce_runs(entries, ("action", "reason", "target"))
    r["failures"] = failures


def _coalesce_runs(entries, key_fields):
    """连续 key_fields 相同的条目合并为一条：firstFrame/lastFrame/count。信息不丢。"""
    out = []
    for e in entries:
        key = tuple(e.get(k) for k in key_fields)
        if out and tuple(out[-1].get(k) for k in key_fields) == key:
            last = out[-1]
            last["count"] = last.get("count", 1) + 1
            last["lastFrame"] = e.get("frame")
            continue
        item = dict(e)
        frame = item.pop("frame", None)
        item["firstFrame"] = frame
        item["lastFrame"] = frame
        item["count"] = 1
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Stage 2：有损封顶（保头尾 + elision 标记）
# ---------------------------------------------------------------------------

def _cap_timeline(r, head, tail):
    tl = r.get("decisionTimeline")
    if not isinstance(tl, list) or len(tl) <= head + tail + 1:
        return
    r["decisionTimeline"] = _head_tail(tl, head, tail, "decisionTimeline")


def _cap_rejected(r, head, tail):
    failures = r.get("failures") or {}
    entries = failures.get("rejected")
    if not isinstance(entries, list) or len(entries) <= head + tail + 1:
        return
    failures["rejected"] = _head_tail(entries, head, tail, "rejected")
    r["failures"] = failures


def _cap_can_afford(r, head, tail):
    failures = r.get("failures") or {}
    entries = failures.get("canAffordBlocked")
    if not isinstance(entries, list) or len(entries) <= head + tail + 1:
        return
    failures["canAffordBlocked"] = _head_tail(entries, head, tail, "canAffordBlocked")
    r["failures"] = failures


def _head_tail(entries, head, tail, label):
    if head <= 0 and tail <= 0:
        return [_elision_marker(len(entries), label)]
    kept_head = entries[:head] if head > 0 else []
    kept_tail = entries[-tail:] if tail > 0 else []
    elided = len(entries) - len(kept_head) - len(kept_tail)
    return kept_head + [_elision_marker(elided, label)] + kept_tail


def _elision_marker(elided, label):
    return {"event": "_ELIDED", "detail": "%s: %d entries elided to fit size limit" % (label, elided),
            "count": elided}


# ---------------------------------------------------------------------------
# Stage 3：丢重可选字段
# ---------------------------------------------------------------------------

def _drop_opp_frames(r):
    traj = r.get("trajectory") or {}
    opp = traj.get("opponent") or {}
    frames = opp.get("frames")
    if isinstance(frames, list) and frames:
        opp["frames"] = [{"_elided": True, "count": len(frames),
                          "note": "opponent sparse frames dropped to fit size limit"}]
        traj["opponent"] = opp
        r["trajectory"] = traj


# ---------------------------------------------------------------------------
# JSON list / text 守卫（index.json / *.md / compact.log）
# ---------------------------------------------------------------------------

def fit_json_list(lst, max_bytes=MAX_FILE_BYTES):
    """index.json 等 JSON list：超预算时保前 N 条 + 一条 elision 标记（合法 JSON）。"""
    if len(_serialize(lst)) <= max_bytes:
        return lst
    marker_base = {"_truncated": True}
    lo, hi = 0, len(lst)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        marker = dict(marker_base)
        marker["note"] = "elided %d entries to fit size limit" % (len(lst) - mid)
        if len(_serialize(lst[:mid] + [marker])) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    marker = dict(marker_base)
    marker["note"] = "elided %d entries to fit size limit" % (len(lst) - lo)
    return lst[:lo] + [marker]


def fit_text(text, max_bytes=MAX_FILE_BYTES):
    """md / compact.log 等文本：超预算时截断并附尾部标记（不切断多字节字符）。"""
    b = text.encode("utf-8")
    if len(b) <= max_bytes:
        return text
    marker = "\n\n[truncated to fit %d-byte size limit; %d bytes elided]\n" % (
        max_bytes, len(b) - max_bytes)
    keep = max_bytes - len(marker.encode("utf-8"))
    if keep <= 0:
        return "[truncated to fit %d-byte size limit; %d bytes elided]" % (
            max_bytes, len(b))
    decoded = b[:keep].decode("utf-8", errors="ignore")
    return decoded + marker


def assert_dir_under_limit(out_dir, max_bytes=MAX_FILE_BYTES):
    """落盘后扫描 out_dir，返回超限文件列表（供 CLI 告警）。空列表 = 全部达标。"""
    oversized = []
    import os
    for root, _dirs, files in os.walk(out_dir):
        for fn in files:
            p = os.path.join(root, fn)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if size > max_bytes:
                oversized.append((p, size))
    return oversized
