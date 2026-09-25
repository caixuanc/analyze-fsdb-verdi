#!/usr/bin/env python3
"""Shared FSDB waveform helpers (fsdbdebug VC format)."""
from __future__ import print_function
import re
import subprocess
import json

from fsdb_env import DEFAULT_FSDBDEBUG, resolve_fsdbdebug


def xtag_to_fs(hi, lo):
    return int(hi) * (2 ** 32) + int(lo)


def fs_to_ns(time_fs, scale_fs=1):
    return float(time_fs) * float(scale_fs) / 1e6


def norm_logic(val):
    v = val.strip().lower()
    if v in ("0", "1"):
        return v
    if v in ("x", "z", "zz"):
        return v.upper()
    return val


def run_fsdbdebug(args, fsdbdebug=DEFAULT_FSDBDEBUG):
    cmd = [fsdbdebug] + args
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    return proc.stdout + proc.stderr


def get_time_scale_fs(fsdb, fsdbdebug=DEFAULT_FSDBDEBUG):
    out = run_fsdbdebug(["-info", fsdb], fsdbdebug)
    m = re.search(r"scale unit\s*:\s*(\d+)\s*fs", out, re.I)
    if m:
        return int(m.group(1))
    return 1


def lookup_vid(fsdb, signal, fsdbdebug=DEFAULT_FSDBDEBUG):
    """Resolve vidcode for hierarchical signal name."""
    import tempfile
    import os
    fd, hier_path = tempfile.mkstemp(suffix=".hier")
    os.close(fd)
    try:
        with open(hier_path, "w") as f:
            f.write(run_fsdbdebug(["-hier_tree", fsdb], fsdbdebug))
        pattern = signal + " "
        with open(hier_path) as f:
            for line in f:
                if "Var: vcd" not in line or pattern not in line:
                    continue
                m = re.search(r"\s(\d+)\s+1B\s", line)
                if m:
                    return int(m.group(1))
    finally:
        os.unlink(hier_path)
    return None


def dump_vc(fsdb, vid, fsdbdebug=DEFAULT_FSDBDEBUG):
    out = run_fsdbdebug(["-vc", "-vidcode", str(vid), fsdb], fsdbdebug)
    vcs = []
    for line in out.splitlines():
        m = re.match(r"\d+ vc: xtag: \((\d+) (\d+)\)\s+val: (\S+)", line)
        if m:
            hi, lo, val = m.groups()
            vcs.append({
                "hi": int(hi), "lo": int(lo),
                "fs": xtag_to_fs(hi, lo), "val": val,
            })
    return vcs


def parse_anchor_edge(edge_str):
    """Parse '0->1', '1->0', etc."""
    m = re.match(r"^([01xXzZ]+)\s*->\s*([01xXzZ]+)$", edge_str.strip())
    if not m:
        raise ValueError("anchor edge must look like 0->1 or 1->0")
    return norm_logic(m.group(1)), norm_logic(m.group(2))


def find_edge_transition(vcs, from_v, to_v):
    prev = None
    for vc in vcs:
        v = norm_logic(vc["val"])
        if v not in ("0", "1"):
            continue
        if prev == from_v and v == to_v:
            return vc
        prev = v
    return None


def stable_value_before(vcs, t_max_fs):
    last = None
    for vc in vcs:
        if vc["fs"] > t_max_fs:
            break
        v = norm_logic(vc["val"])
        if v in ("0", "1"):
            last = v
    return last if last is not None else "—"


def stable_value_after(vcs, t_min_fs):
    for vc in vcs:
        if vc["fs"] < t_min_fs:
            continue
        v = norm_logic(vc["val"])
        if v in ("0", "1"):
            return v
    return "—"


def classify_after_region(vcs, t_min_fs, toggle_threshold=8):
    """Return stable level or 'toggle' if many edges after t_min."""
    vals = []
    edges = 0
    prev = None
    for vc in vcs:
        if vc["fs"] < t_min_fs:
            continue
        v = norm_logic(vc["val"])
        if v not in ("0", "1"):
            continue
        vals.append(v)
        if prev is not None and v != prev:
            edges += 1
        prev = v
    if edges >= toggle_threshold:
        return "toggle"
    return vals[-1] if vals else "—"


def shorten_signal(path, max_len=48):
    if len(path) <= max_len:
        return path
    parts = path.split(".")
    if len(parts) <= 3:
        return path[: max_len - 3] + "..."
    return "...." + ".".join(parts[-3:])


def logic_points(vcs):
    """Return [(time_fs, '0'|'1'), ...] for binary transitions only."""
    return [
        (vc["fs"], norm_logic(vc["val"]))
        for vc in vcs
        if norm_logic(vc["val"]) in ("0", "1")
    ]


def level_at_time(vcs, t_fs):
    """Last stable 0/1 level at or before t_fs."""
    level = None
    for vc in vcs:
        if vc["fs"] > t_fs:
            break
        v = norm_logic(vc["val"])
        if v in ("0", "1"):
            level = v
    return level


def collect_edges(vcs, t_start_fs):
    """Collect 0/1 edges at or after t_start_fs. Includes edge at t_start_fs."""
    pts = logic_points(vcs)
    if not pts:
        return [], None

    level = level_at_time(vcs, t_start_fs)
    if level is None:
        level = pts[0][1]

    edges = []
    prev_v = level
    for t, v in pts:
        if t < t_start_fs:
            prev_v = v
            continue
        if v != prev_v:
            edges.append({"time_fs": t, "from": prev_v, "to": v})
        prev_v = v
    return edges, level


def resolve_anchor_transition(raw, anchor_cfg, defaults=None):
    """
    Resolve anchor edge time from dumped VC data.

    Returns dict with keys: signal, edge, status, transition_fs, transition_ns,
    timeline (optional), error (optional).
    """
    defaults = defaults or {}
    asig = anchor_cfg.get("signal")
    edge = anchor_cfg.get("edge", defaults.get("edge", "0->1"))
    info = {"signal": asig, "edge": edge}

    ent = raw.get(asig) if asig else None
    if not ent or not ent.get("vcs"):
        info["status"] = "anchor not found or no VC"
        info["error"] = "missing_anchor_vc"
        return info

    from_v, to_v = parse_anchor_edge(edge)
    tr = find_edge_transition(ent["vcs"], from_v, to_v)
    if tr:
        info["transition_fs"] = tr["fs"]
        info["status"] = "edge {} found".format(edge)
    else:
        info["status"] = "no {} on anchor".format(edge)
        info["error"] = "no_anchor_edge"
    return info


def compute_duty_cycle(vcs, t_start_fs, scale_fs=1, num_cycles=10,
                       start_offset_fs=0):
    """
    Average duty cycle over the first num_cycles complete periods after t_start.

    Period is measured rising-edge to rising-edge. Returns a result dict with
    status ok | insufficient_cycles | no_complete_periods | no_data.
    """
    t_measure = t_start_fs + start_offset_fs
    edges, level_at_start = collect_edges(vcs, t_measure)
    pts = logic_points(vcs)

    if not pts:
        return {"status": "no_data"}

    rising = [e for e in edges if e["from"] == "0" and e["to"] == "1"]
    if len(rising) < 2:
        return {
            "status": "insufficient_cycles",
            "edges_after_start": len(edges),
            "rising_edges": len(rising),
            "level_at_start": level_at_start,
            "final": pts[-1][1],
        }

    periods_fs = []
    high_fs = []
    use_rising = rising[: num_cycles + 1]
    for i in range(min(num_cycles, len(use_rising) - 1)):
        t_rise = use_rising[i]["time_fs"]
        t_next = use_rising[i + 1]["time_fs"]
        period = t_next - t_rise
        if period <= 0:
            continue
        fall_t = None
        for e in edges:
            if e["from"] == "1" and e["to"] == "0" and t_rise < e["time_fs"] < t_next:
                fall_t = e["time_fs"]
                break
        if fall_t is None:
            continue
        periods_fs.append(period)
        high_fs.append(fall_t - t_rise)

    if not periods_fs:
        return {
            "status": "no_complete_periods",
            "edges_after_start": len(edges),
            "rising_edges": len(rising),
            "level_at_start": level_at_start,
        }

    avg_period = sum(periods_fs) / len(periods_fs)
    avg_high = sum(high_fs) / len(high_fs)
    avg_low = avg_period - avg_high
    duty_pct = 100.0 * avg_high / avg_period if avg_period else 0.0
    period_ns = fs_to_ns(avg_period, scale_fs)

    return {
        "status": "ok",
        "cycles_measured": len(periods_fs),
        "duty_pct": duty_pct,
        "period_ns": period_ns,
        "high_ns": fs_to_ns(avg_high, scale_fs),
        "low_ns": fs_to_ns(avg_low, scale_fs),
        "freq_mhz": (1e3 / period_ns) if period_ns else 0.0,
        "edges_after_start": len(edges),
        "rising_edges": len(rising),
        "level_at_start": level_at_start,
        "final": pts[-1][1],
    }


def evaluate_expect(result, expect):
    """
    Compare a numeric check result against optional expect bounds.
    expect keys use suffix _min / _max on result field names (e.g. duty_pct_min).
    Returns list of failure strings (empty = pass).
    """
    if not expect:
        return []
    failures = []
    for key, bound in expect.items():
        if key.endswith("_min"):
            field = key[:-4]
            val = result.get(field)
            if val is not None and val < bound:
                failures.append("{} {:.4g} < min {:.4g}".format(field, val, bound))
        elif key.endswith("_max"):
            field = key[:-4]
            val = result.get(field)
            if val is not None and val > bound:
                failures.append("{} {:.4g} > max {:.4g}".format(field, val, bound))
    return failures
