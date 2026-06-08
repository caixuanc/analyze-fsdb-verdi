#!/usr/bin/env python3
"""Parse fsdbdebug -vc dumps; report before/after anchor transition.

Usage:
  parse_fsdb_vc.py fsdb_analysis_out/case3_vc.txt
  parse_fsdb_vc.py fsdb_analysis_out/   # all case*_vc.txt
"""
from __future__ import print_function
import re
import sys
from pathlib import Path


def xtag_to_fs(hi, lo):
    return int(hi) * (2 ** 32) + int(lo)


def norm(v):
    v = v.strip().lower()
    return v if v in ("0", "1") else v


def parse_file(path):
    text = path.read_text()
    anchor_name = None
    data = {}
    for line in text.splitlines():
        m = re.match(r"^anchor: (.+)$", line)
        if m:
            anchor_name = m.group(1).strip()
            continue
        m = re.match(r"^=== (.+?) (?:\(vid=|\===)", line)
        if m:
            name = m.group(1).strip()
            if name.startswith("ANCHOR "):
                cur = "__anchor__"
            else:
                cur = name
            data[cur] = []
            continue
        m = re.match(r"\d+ vc: xtag: \((\d+) (\d+)\)\s+val: (\S+)", line)
        if m and cur:
            hi, lo, val = m.groups()
            data[cur].append({"fs": xtag_to_fs(hi, lo), "val": val})
    return anchor_name, data


def find_transition(vcs):
    prev = None
    for vc in vcs:
        v = norm(vc["val"])
        if v not in ("0", "1"):
            continue
        if prev == "0" and v == "1":
            return vc["fs"]
        prev = v
    return None


def stable_at(vcs, t_max):
    last = "?"
    for vc in vcs:
        if vc["fs"] > t_max:
            break
        v = norm(vc["val"])
        if v in ("0", "1"):
            last = v
    return last


def summarize(path):
    anchor_name, data = parse_file(path)
    anc = data.get("__anchor__", [])
    t_trans = find_transition(anc)
    if t_trans is None:
        t_before = 0
        t_after = 10 ** 15
        note = "no 0->1 on anchor"
    else:
        t_before = t_trans - 1000
        t_after = t_trans + 1000000000
        note = "anchor 0->1 @ {:.1f} ns".format(t_trans / 1e6)

    rows = []
    for sig, vcs in sorted(data.items()):
        if sig == "__anchor__":
            continue
        rows.append((sig, stable_at(vcs, t_before), stable_at(vcs, t_after)))
    return anchor_name, note, rows


def main():
    paths = []
    if len(sys.argv) < 2:
        print("Usage: parse_fsdb_vc.py <file_or_dir>", file=sys.stderr)
        sys.exit(1)
    p = Path(sys.argv[1])
    if p.is_dir():
        paths = sorted(p.glob("case*_vc.txt"))
    else:
        paths = [p]

    print("{:<40} {:<28} {:<8} {:<8} {}".format(
        "file", "signal", "before", "after", "notes"))
    for path in paths:
        anchor, note, rows = summarize(path)
        for sig, b, a in rows:
            print("{:<40} {:<28} {:<8} {:<8} {}".format(
                path.name, sig[:28], b, a, note))
        if anchor:
            print("  anchor: {}".format(anchor))


if __name__ == "__main__":
    main()
