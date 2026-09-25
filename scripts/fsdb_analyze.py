#!/usr/bin/env python3
"""
Modular FSDB signal analyzer (fsdbdebug backend).

Usage:
  # Config file (multi-FSDB):
  python3 fsdb_analyze.py -c analysis.json -o report.txt

  # Single FSDB, CLI:
  python3 fsdb_analyze.py --fsdb path.fsdb --signals top.a,top.b \\
      --anchor top.ctrl.lock --edge 0->1

  # Dump only (raw VC):
  python3 fsdb_analyze.py -c analysis.json --dump-only -o ./vc_out
"""
from __future__ import print_function
import argparse
import json
import os
import sys
from pathlib import Path

# allow import from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fsdb_lib as lib
import fsdb_checks as checks
import fsdb_env as env


def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    return normalize_config(cfg)


def normalize_config(cfg):
    """Merge top-level signals/anchor/checks into each run if omitted."""
    default_signals = cfg.get("signals", [])
    default_anchor = cfg.get("anchor")
    runs = cfg.get("runs", cfg.get("fsdbs", []))
    if not runs:
        raise ValueError("config must contain 'runs' or 'fsdbs' list")
    out_runs = []
    for r in runs:
        run = dict(r)
        run.setdefault("signals", list(default_signals))
        if "anchor" not in run and default_anchor:
            run["anchor"] = dict(default_anchor)
        run["_resolved_checks"] = checks.resolve_checks_for_run(run, cfg)
        out_runs.append(run)
    cfg["runs"] = out_runs
    if not cfg.get("fsdbdebug"):
        path, _src = env.resolve_fsdbdebug()
        cfg["fsdbdebug"] = path
    cfg.setdefault("anchor_defaults", {
        "edge": "0->1",
        "before_offset_fs": 1000,
        "after_offset_fs": 1000000000,
        "toggle_threshold": 8,
    })
    return cfg


def config_from_args(args):
    if not args.fsdb:
        raise ValueError("--fsdb required without -c")
    signals = [s.strip() for s in args.signals.split(",") if s.strip()]
    run = {
        "id": args.id or "1",
        "label": args.label or "",
        "fsdb": args.fsdb,
        "signals": signals,
    }
    if args.anchor:
        run["anchor"] = {
            "signal": args.anchor,
            "edge": args.edge,
        }
    cfg = {
        "runs": [run],
        "fsdbdebug": args.fsdbdebug,
        "anchor_defaults": {
            "edge": args.edge,
            "before_offset_fs": 1000,
            "after_offset_fs": 1000000000,
            "toggle_threshold": args.toggle_threshold,
        },
    }
    if args.duty_cycle:
        duty_sigs = signals
        if args.duty_signals:
            duty_sigs = [s.strip() for s in args.duty_signals.split(",") if s.strip()]
        if not args.anchor:
            raise ValueError("--duty-cycle requires --anchor")
        duty_check = {
            "type": "duty_cycle",
            "id": "duty_cycle_cli",
            "anchor": {"signal": args.anchor, "edge": args.edge},
            "signals": duty_sigs,
            "params": {"cycles": args.duty_cycles},
        }
        if args.duty_min is not None or args.duty_max is not None:
            duty_check["expect"] = {}
            if args.duty_min is not None:
                duty_check["expect"]["duty_pct_min"] = args.duty_min
            if args.duty_max is not None:
                duty_check["expect"]["duty_pct_max"] = args.duty_max
        cfg["checks"] = [duty_check]
    return cfg


def analyze_run(run, cfg, dump_only=False):
    fsdb = run["fsdb"]
    fsdbdebug = cfg.get("fsdbdebug", lib.DEFAULT_FSDBDEBUG)
    result = {
        "id": run.get("id", "?"),
        "label": run.get("label", ""),
        "fsdb": fsdb,
        "missing_fsdb": not os.path.isfile(fsdb),
        "signals": {},
        "anchor": None,
        "checks": [],
        "errors": [],
    }
    if result["missing_fsdb"]:
        result["errors"].append("FSDB file not found")
        return result

    scale_fs = lib.get_time_scale_fs(fsdb, fsdbdebug)
    result["time_scale_fs"] = scale_fs

    all_sigs = list(run.get("signals", []))
    anchor_cfg = run.get("anchor")
    if anchor_cfg and anchor_cfg.get("signal"):
        if anchor_cfg["signal"] not in all_sigs:
            all_sigs.append(anchor_cfg["signal"])

    resolved_checks = run.get("_resolved_checks", [])
    for sig in checks.collect_check_signals(resolved_checks):
        if sig not in all_sigs:
            all_sigs.append(sig)

    raw = {}
    for sig in all_sigs:
        vid = lib.lookup_vid(fsdb, sig, fsdbdebug)
        if vid is None:
            raw[sig] = None
            result["errors"].append("signal not in FSDB: {}".format(sig))
            continue
        raw[sig] = {"vid": vid, "vcs": lib.dump_vc(fsdb, vid, fsdbdebug)}

    if dump_only:
        result["raw"] = raw
        return result

    defaults = cfg.get("anchor_defaults", {})
    t_before = 0
    t_after = 10 ** 18
    anchor_info = None

    if anchor_cfg and anchor_cfg.get("signal"):
        asig = anchor_cfg["signal"]
        edge = anchor_cfg.get("edge", defaults.get("edge", "0->1"))
        from_v, to_v = lib.parse_anchor_edge(edge)
        avcs = raw.get(asig, {}).get("vcs") if raw.get(asig) else None
        anchor_info = {"signal": asig, "edge": edge}
        if not avcs:
            anchor_info["status"] = "anchor not found or no VC"
        else:
            tr = lib.find_edge_transition(avcs, from_v, to_v)
            if tr:
                t_fs = tr["fs"]
                anchor_info["transition_ns"] = lib.fs_to_ns(t_fs, scale_fs)
                anchor_info["status"] = "edge {} @ {:.3f} ns".format(
                    edge, anchor_info["transition_ns"])
                boff = anchor_cfg.get(
                    "before_offset_fs", defaults.get("before_offset_fs", 1000))
                aoff = anchor_cfg.get(
                    "after_offset_fs", defaults.get("after_offset_fs", 1000000000))
                t_before = t_fs - boff
                t_after = t_fs + aoff
            else:
                anchor_info["status"] = "no {} on anchor".format(edge)
            anchor_info["timeline"] = [
                {
                    "time_ns": lib.fs_to_ns(vc["fs"], scale_fs),
                    "value": lib.norm_logic(vc["val"]),
                }
                for vc in (avcs or [])
            ]
        result["anchor"] = anchor_info

    toggle_thr = defaults.get("toggle_threshold", 8)
    use_anchor = anchor_info and anchor_info.get("transition_ns") is not None

    for sig in run.get("signals", []):
        ent = raw.get(sig)
        if not ent:
            result["signals"][sig] = {"status": "NOT_FOUND"}
            continue
        vcs = ent["vcs"]
        info = {
            "vid": ent["vid"],
            "vc_count": len(vcs),
            "initial": lib.norm_logic(vcs[0]["val"]) if vcs else "—",
            "final": lib.norm_logic(vcs[-1]["val"]) if vcs else "—",
        }
        if use_anchor:
            info["before_anchor"] = lib.stable_value_before(vcs, t_before)
            info["after_anchor"] = lib.classify_after_region(
                vcs, t_after, toggle_thr)
        elif vcs:
            info["timeline"] = [
                {"time_ns": lib.fs_to_ns(vc["fs"], scale_fs),
                 "value": lib.norm_logic(vc["val"])}
                for vc in vcs[:20]
            ]
            if len(vcs) > 20:
                info["timeline_note"] = "{} more transitions omitted".format(
                    len(vcs) - 20)
        result["signals"][sig] = info

    if resolved_checks:
        result["checks"] = checks.run_all_checks(
            resolved_checks, raw, scale_fs, defaults)

    return result


def format_report(results, cfg):
    lines = []
    sep = "=" * 72
    lines.append(sep)
    lines.append("FSDB SIGNAL ANALYSIS REPORT")
    lines.append(sep)
    lines.append("")

    for res in results:
        lines.append("-" * 72)
        title = "Run {}".format(res["id"])
        if res.get("label"):
            title += " ({})".format(res["label"])
        lines.append(title)
        lines.append("-" * 72)
        lines.append("FSDB: {}".format(res["fsdb"]))
        if res.get("missing_fsdb"):
            lines.append("STATUS: ERROR — file not found")
            for e in res.get("errors", []):
                lines.append("  - {}".format(e))
            lines.append("")
            continue

        lines.append("Time scale: {} fs per unit".format(res.get("time_scale_fs", 1)))
        for e in res.get("errors", []):
            lines.append("Warning: {}".format(e))

        anc = res.get("anchor")
        if anc:
            lines.append("")
            lines.append("Anchor: {}".format(anc.get("signal", "")))
            lines.append("  Edge: {}".format(anc.get("edge", "")))
            lines.append("  Status: {}".format(anc.get("status", "")))
            if anc.get("transition_ns") is not None:
                lines.append("  Transition time: {:.3f} ns".format(
                    anc["transition_ns"]))
            if anc.get("timeline"):
                lines.append("  Anchor timeline:")
                for pt in anc["timeline"]:
                    lines.append("    @ {:>12.3f} ns  = {}".format(
                        pt["time_ns"], pt["value"]))

        lines.append("")
        lines.append("Signals:")
        hdr = "  {:<50} {:>8} {:>8} {:>8} {:>6}".format(
            "Signal", "Before", "After", "Final", "#VC")
        if not anc:
            hdr = "  {:<50} {:>8} {:>8} {:>6}".format(
                "Signal", "Initial", "Final", "#VC")
        lines.append(hdr)
        lines.append("  " + "-" * (len(hdr) - 2))

        for sig, info in sorted(res.get("signals", {}).items()):
            short = lib.shorten_signal(sig, 50)
            if anc and "before_anchor" in info:
                lines.append("  {:<50} {:>8} {:>8} {:>8} {:>6}".format(
                    short,
                    info.get("before_anchor", "—"),
                    info.get("after_anchor", "—"),
                    info.get("final", "—"),
                    info.get("vc_count", 0),
                ))
            else:
                lines.append("  {:<50} {:>8} {:>8} {:>6}".format(
                    short,
                    info.get("initial", "—"),
                    info.get("final", "—"),
                    info.get("vc_count", 0),
                ))
            if info.get("status") == "NOT_FOUND":
                lines[-1] += "  [NOT FOUND]"

        if res.get("checks"):
            lines.append("")
            lines.append("Checks:")
            lines.extend(checks.format_checks_report(res["checks"]))

        lines.append("")

    lines.append(sep)
    lines.append("End of report ({} run(s))".format(len(results)))
    lines.append(sep)
    return "\n".join(lines)


def write_dump_files(results, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for res in results:
        if "raw" not in res:
            continue
        path = out / "run_{}_vc.txt".format(res["id"])
        with open(path, "w") as f:
            f.write("id: {}\n".format(res["id"]))
            f.write("fsdb: {}\n".format(res["fsdb"]))
            for sig, ent in res["raw"].items():
                f.write("\n=== {} (vid={}) ===\n".format(
                    sig, ent["vid"] if ent else "NA"))
                if not ent:
                    continue
                for i, vc in enumerate(ent["vcs"], 1):
                    f.write("{} vc: xtag: ({} {})  val: {}\n".format(
                        i, vc["hi"], vc["lo"], vc["val"]))
        print("Wrote {}".format(path), file=sys.stderr)


def _first_fsdb_from_cfg(cfg):
    runs = cfg.get("runs") or []
    if runs:
        return runs[0].get("fsdb")
    return None


def main():
    ap = argparse.ArgumentParser(description="Modular FSDB signal analyzer")
    ap.add_argument("-c", "--config", help="JSON config file")
    ap.add_argument("-o", "--output", help="Write report to file (default: stdout)")
    ap.add_argument("--dump-only", action="store_true", help="Only dump raw VC files")
    ap.add_argument("--fsdbdebug", default=None,
                    help="Path to fsdbdebug (auto-detected if omitted)")
    ap.add_argument("--preflight", action="store_true",
                    help="Check dependencies only; do not analyze")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="Skip dependency check before analysis")

    ap.add_argument("--fsdb", help="Single FSDB path (CLI mode)")
    ap.add_argument("--signals", help="Comma-separated signal list (CLI mode)")
    ap.add_argument("--anchor", help="Anchor signal (optional)")
    ap.add_argument("--edge", default="0->1", help="Anchor edge (default 0->1)")
    ap.add_argument("--id", default="1", help="Run id (CLI mode)")
    ap.add_argument("--label", default="", help="Run label (CLI mode)")
    ap.add_argument("--toggle-threshold", type=int, default=8,
                    help="VC toggles after anchor to call 'toggle'")

    ap.add_argument("--duty-cycle", action="store_true",
                    help="Run duty_cycle check (requires --anchor)")
    ap.add_argument("--duty-signals",
                    help="Comma-separated signals for duty cycle (default: --signals)")
    ap.add_argument("--duty-cycles", type=int, default=10,
                    help="Cycles to average for duty cycle (default 10)")
    ap.add_argument("--duty-min", type=float,
                    help="Optional min duty %% for PASS/FAIL")
    ap.add_argument("--duty-max", type=float,
                    help="Optional max duty %% for PASS/FAIL")

    args = ap.parse_args()
    config_fsdbdebug = None
    if args.config:
        with open(args.config) as f:
            raw_cfg = json.load(f)
        config_fsdbdebug = raw_cfg.get("fsdbdebug")
        cfg = normalize_config(raw_cfg)
    elif args.fsdb and args.signals:
        cfg = config_from_args(args)
        cfg = normalize_config(cfg)
    elif args.preflight:
        cfg = {"runs": [], "anchor_defaults": {"toggle_threshold": 8}}
    else:
        ap.error("Provide -c config.json OR --fsdb with --signals")

    resolved_path, resolved_source = env.resolve_fsdbdebug(
        explicit=args.fsdbdebug or config_fsdbdebug)
    cfg["fsdbdebug"] = resolved_path
    cfg.setdefault("anchor_defaults", {})["toggle_threshold"] = args.toggle_threshold

    probe_fsdb = args.fsdb or _first_fsdb_from_cfg(cfg)
    if args.preflight or not args.skip_preflight:
        pf = env.run_preflight(
            fsdbdebug=args.fsdbdebug or config_fsdbdebug,
            fsdb=probe_fsdb,
        )
        if args.preflight:
            print(env.format_preflight_report(pf))
            sys.exit(0 if pf["ok"] else 1)
        if not pf["ok"]:
            print(env.format_preflight_report(pf), file=sys.stderr)
            sys.exit(1)

    results = [analyze_run(r, cfg, dump_only=args.dump_only) for r in cfg["runs"]]

    if args.dump_only:
        out_dir = args.output or "./fsdb_analysis_out"
        write_dump_files(results, out_dir)
        return

    report = format_report(results, cfg)
    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print("Report written to {}".format(args.output), file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
