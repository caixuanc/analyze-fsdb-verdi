#!/usr/bin/env python3
"""
Pluggable FSDB check framework.

Each check type registers a handler in CHECK_HANDLERS. Handlers receive a
normalized check config, dumped VC data (raw), time scale, and defaults.

Add new check types here without changing the core analyze loop.
"""
from __future__ import print_function
import copy

import fsdb_lib as lib

# Default params per check type (merged with check.params from config)
DEFAULT_PARAMS = {
    "duty_cycle": {
        "cycles": 10,
        "start_offset_fs": 0,
    },
}


def merge_check_config(check, run, cfg):
    """
    Normalize one check entry: inherit anchor/signals from run or cfg when omitted.
    """
    out = copy.deepcopy(check)
    out.setdefault("id", out.get("type", "check"))
    out.setdefault("label", "")

    if "anchor" not in out:
        if run.get("anchor"):
            out["anchor"] = copy.deepcopy(run["anchor"])
        elif cfg.get("anchor"):
            out["anchor"] = copy.deepcopy(cfg["anchor"])

    if "signals" not in out or not out["signals"]:
        out["signals"] = list(run.get("signals", cfg.get("signals", [])))

    params = dict(DEFAULT_PARAMS.get(out.get("type"), {}))
    params.update(out.get("params") or {})
    out["params"] = params
    out["expect"] = out.get("expect") or {}
    return out


def resolve_checks_for_run(run, cfg):
    """Merge top-level checks with run-local checks (run checks appended)."""
    merged = []
    for check in cfg.get("checks", []):
        merged.append(merge_check_config(check, run, cfg))
    for check in run.get("checks", []):
        merged.append(merge_check_config(check, run, cfg))
    return merged


def collect_check_signals(checks):
    """All hierarchical signal names required by checks (probes + anchors)."""
    sigs = []
    seen = set()
    for check in checks:
        for sig in check.get("signals", []):
            if sig not in seen:
                seen.add(sig)
                sigs.append(sig)
        anc = check.get("anchor") or {}
        asig = anc.get("signal")
        if asig and asig not in seen:
            seen.add(asig)
            sigs.append(asig)
    return sigs


def run_duty_cycle_check(check, raw, scale_fs, defaults):
    """Measure average duty cycle per signal after an anchor transition."""
    result = {
        "id": check.get("id"),
        "type": "duty_cycle",
        "label": check.get("label", ""),
        "status": "ok",
        "anchor": None,
        "signals": {},
        "errors": [],
    }

    anchor_cfg = check.get("anchor")
    if not anchor_cfg or not anchor_cfg.get("signal"):
        result["status"] = "error"
        result["errors"].append("duty_cycle requires anchor.signal")
        return result

    anchor_info = lib.resolve_anchor_transition(raw, anchor_cfg, defaults)
    result["anchor"] = {
        "signal": anchor_info.get("signal"),
        "edge": anchor_info.get("edge"),
        "status": anchor_info.get("status"),
    }

    if anchor_info.get("transition_fs") is None:
        result["status"] = "error"
        result["errors"].append(anchor_info.get("status", "anchor unresolved"))
        return result

    t_start = anchor_info["transition_fs"]
    result["anchor"]["transition_ns"] = lib.fs_to_ns(t_start, scale_fs)
    params = check["params"]
    expect = check.get("expect") or {}

    for sig in check.get("signals", []):
        ent = raw.get(sig)
        if not ent or not ent.get("vcs"):
            result["signals"][sig] = {"status": "NOT_FOUND"}
            result["errors"].append("signal not in FSDB: {}".format(sig))
            continue

        meas = lib.compute_duty_cycle(
            ent["vcs"],
            t_start,
            scale_fs=scale_fs,
            num_cycles=params.get("cycles", 10),
            start_offset_fs=params.get("start_offset_fs", 0),
        )
        entry = dict(meas)
        failures = lib.evaluate_expect(meas, expect)
        if failures:
            entry["expect"] = "FAIL"
            entry["expect_failures"] = failures
            result["errors"].extend(
                ["{}: {}".format(lib.shorten_signal(sig, 40), f) for f in failures]
            )
        elif expect:
            entry["expect"] = "PASS"
        result["signals"][sig] = entry

    if result["errors"] and result["status"] == "ok":
        result["status"] = "fail" if any(
            s.get("expect") == "FAIL" for s in result["signals"].values()
        ) else "warn"

    return result


CHECK_HANDLERS = {
    "duty_cycle": run_duty_cycle_check,
}


def run_check(check, raw, scale_fs, defaults):
    """Dispatch one check to its handler."""
    handler = CHECK_HANDLERS.get(check.get("type"))
    if not handler:
        return {
            "id": check.get("id"),
            "type": check.get("type"),
            "status": "error",
            "errors": ["unknown check type: {}".format(check.get("type"))],
        }
    return handler(check, raw, scale_fs, defaults)


def run_all_checks(checks, raw, scale_fs, defaults):
    """Run every check for one FSDB run."""
    return [run_check(c, raw, scale_fs, defaults) for c in checks]


def format_checks_report(check_results):
    """Format check results as plain-text report sections."""
    lines = []
    for cr in check_results:
        title = "Check: {} ({})".format(cr.get("id", "?"), cr.get("type", "?"))
        if cr.get("label"):
            title += " — {}".format(cr["label"])
        lines.append("")
        lines.append(title)
        lines.append("  Status: {}".format(cr.get("status", "?")))
        for err in cr.get("errors", []):
            lines.append("  Error: {}".format(err))

        anc = cr.get("anchor")
        if anc:
            lines.append("  Anchor: {}  edge={}".format(
                anc.get("signal", ""), anc.get("edge", "")))
            lines.append("  Anchor status: {}".format(anc.get("status", "")))
            if anc.get("transition_ns") is not None:
                lines.append("  Anchor time: {:.3f} ns".format(anc["transition_ns"]))

        if cr.get("type") == "duty_cycle" and cr.get("signals"):
            lines.append("")
            hdr = "    {:<48} {:>7} {:>10} {:>10} {:>10} {:>6} {:>6}".format(
                "Signal", "Duty%", "Period", "High", "Freq", "Cy", "Exp")
            lines.append(hdr)
            lines.append("    " + "-" * (len(hdr) - 4))
            for sig, info in sorted(cr.get("signals", {}).items()):
                short = lib.shorten_signal(sig, 48)
                if info.get("status") == "NOT_FOUND":
                    lines.append("    {:<48} NOT_FOUND".format(short))
                    continue
                if info.get("status") == "ok":
                    exp = info.get("expect", "—")
                    lines.append(
                        "    {:<48} {:>6.2f}% {:>9.3f}ns {:>9.3f}ns {:>9.4f}M {:>6} {:>6}".format(
                            short,
                            info.get("duty_pct", 0),
                            info.get("period_ns", 0),
                            info.get("high_ns", 0),
                            info.get("freq_mhz", 0),
                            info.get("cycles_measured", 0),
                            exp,
                        ))
                else:
                    lines.append("    {:<48} {} (edges={}, rising={})".format(
                        short,
                        info.get("status", "?"),
                        info.get("edges_after_start", "?"),
                        info.get("rising_edges", "?"),
                    ))
    return lines
