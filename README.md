# WIP 🚧

# analyze-fsdb-verdi

Batch FSDB waveform analysis for DV regression triage. Provide FSDB file(s) and signal names; the tool dumps value changes via Synopsys `fsdbdebug` and produces a human-readable report — including optional duty-cycle checks with PASS/FAIL bounds.

Works as a **standalone Python tool** or as a **Cursor Agent Skill** that guides the AI to run analysis for you.

---

## Table of contents

- [Overview](#overview)
- [How it works](#how-it-works)
- [File structure](#file-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Integration with Cursor](#integration-with-cursor)
- [Input](#input)
- [Output](#output)
- [Usage examples](#usage-examples)
- [Modular checks](#modular-checks)
- [Sharing with colleagues](#sharing-with-colleagues)
- [Troubleshooting](#troubleshooting)
- [Further reading](#further-reading)

---

## Overview

| Item | Detail |
|------|--------|
| **Purpose** | Analyze `inter.fsdb` (or any FSDB) without opening Verdi GUI |
| **Backend** | `fsdbdebug` from Synopsys Verdi V-2023.12 |
| **Entry point** | `scripts/fsdb_analyze.py` |
| **Config** | JSON file or CLI arguments |
| **Scope** | Single FSDB or many FSDBs in one run |
| **Python deps** | None (stdlib only) |

**Typical use cases:**

- Check signal level before/after a lock or enable event
- Measure clock duty cycle after PLL lock
- Batch-compare the same signals across regression seeds
- Triage failing tests by reading a text report instead of waveforms

---

## How it works

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Input      │     │  fsdb_analyze.py │     │  Output     │
│  FSDB path  │────▶│  + fsdb_checks   │────▶│  report.txt │
│  signals    │     │  + fsdb_lib      │     │  (stdout)   │
│  anchor     │     └────────┬─────────┘     └─────────────┘
│  checks[]   │              │
└─────────────┘              ▼
                    ┌─────────────────┐
                    │  fsdbdebug      │
                    │  -hier_tree     │  resolve signal → vidcode
                    │  -vc -vidcode   │  dump value changes
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │  inter.fsdb     │
                    └─────────────────┘
```

**Per FSDB run, the tool:**

1. Confirms the FSDB file exists
2. Resolves each signal name to a `vidcode` (unique per FSDB — never reused across files)
3. Dumps value-change (VC) records for each signal
4. If an **anchor** is set, finds the specified edge (e.g. `0->1`) and reports Before / After / Final per signal
5. Runs any **checks** (e.g. `duty_cycle`) with their own anchor, signals, and optional PASS/FAIL bounds
6. Writes a plain-text report

---

## File structure

```
analyze-fsdb-verdi/
├── README.md                 ← this guide
├── SKILL.md                  ← Cursor agent instructions (auto-trigger)
├── config.schema.md          ← JSON config reference
├── reference.md              ← fsdbdebug / arc shell cheat sheet
├── IMPROVING.md              ← how to add new check types
│
├── config/                   ← copy-and-edit templates
│   ├── example.json          multi-FSDB, anchor before/after
│   ├── single.example.json   single FSDB
│   ├── duty_cycle.example.json
│   └── multi_check.example.json
│
├── examples/
│   └── km_gppll.md           project-specific signal/anchor notes
│
└── scripts/
    ├── fsdb_analyze.py       ★ main entry point
    ├── fsdb_env.py           dependency preflight + tool auto-detection
    ├── fsdb_lib.py           VC parsing, anchor, duty-cycle math
    ├── fsdb_checks.py        pluggable check registry
    ├── dump_fsdb_vc.sh       legacy shell wrapper
    └── parse_fsdb_vc.py      legacy VC file parser
```

| File | Role |
|------|------|
| `fsdb_analyze.py` | CLI + config loader, orchestrates runs, formats report |
| `fsdb_lib.py` | Low-level FSDB helpers (time scale, vid lookup, VC dump, duty math) |
| `fsdb_checks.py` | Check type registry; add new analysis types here |
| `SKILL.md` | Tells Cursor when and how to invoke the tool automatically |

---

## Prerequisites

1. **Python 3** (any recent version with stdlib)
2. **`fsdbdebug`** from Synopsys Verdi — auto-detected (see below)
3. **Arc shell** (Intel environment) — optional if `fsdbdebug` is directly executable

### Preflight (dependency check)

```bash
python3 scripts/fsdb_env.py
python3 scripts/fsdb_env.py --fsdb /path/to/inter.fsdb   # also probe FSDB
python3 scripts/fsdb_analyze.py --preflight              # same check via main entry
```

Preflight verifies Python, locates `fsdbdebug`, tests it runs, discovers ARC/Verdi if needed, and prints **READY** or **NOT READY** with fix suggestions.

**Auto-resolution order for `fsdbdebug`:**

1. `--fsdbdebug` CLI flag or `"fsdbdebug"` in JSON config
2. `$FSDBDEBUG` environment variable
3. `config/env.local.json` (per-user site overrides)
4. Built-in default path (`V-2023.12`)
5. `fsdbdebug` on `PATH`
6. `arc resource-use synopsys_verdi/<version>` PATH discovery

**Per-site config for colleagues:** copy `config/env.example.json` to `config/env.local.json` and edit `fsdbdebug`, `arc_bin`, `arc_verdi_resource`, `arc_worksets`.

**Arc shell** (when preflight suggests it):

```bash
/p/psg/ctools/arc/2019.1/bin/arc shell --no-inherit km_dv/2025WW48 synopsys_verdi/V-2023.12 -- <command>
```

Analysis runs preflight automatically before each run (use `--skip-preflight` to bypass).

---

## Installation

### Personal install (recommended — available in all Cursor projects)

```bash
# From a shared tarball or git clone:
mkdir -p ~/.cursor/skills
cp -r analyze-fsdb-verdi ~/.cursor/skills/

# Or extract tarball:
cd ~/.cursor/skills
tar xzvf /path/to/analyze-fsdb-verdi.tar.gz
```

### Project install (shared with team via repo)

```bash
mkdir -p <your-project>/.cursor/skills
cp -r analyze-fsdb-verdi <your-project>/.cursor/skills/
# Commit .cursor/skills/analyze-fsdb-verdi/ to your project repo
```

### Scripts only (no Cursor)

Copy the `scripts/`, `config/`, and doc files anywhere on your PATH or project tree. Run `python3 fsdb_analyze.py` directly.

> **Note:** Do **not** install into `~/.cursor/skills-cursor/` — that directory is reserved for Cursor built-in skills.

---

## Integration with Cursor

Once installed under `~/.cursor/skills/analyze-fsdb-verdi/` (or `.cursor/skills/` in a project), Cursor discovers `SKILL.md` automatically.

The agent is triggered when you ask things like:

- "Analyze inter.fsdb for dsm_lock behavior"
- "Check duty cycle after lock2core"
- "Compare these FSDB regression waveforms"

**Agent workflow:**

1. Confirm FSDB paths exist
2. Build a JSON config or CLI command from your signal/anchor/check request
3. Run `fsdb_analyze.py` (inside arc shell if needed)
4. Return and explain the report (anchor time, PASS/FAIL, NOT_FOUND signals)

You can also run the tool yourself without involving the agent — see [Usage examples](#usage-examples).

---

## Input

### Required

| Input | Description |
|-------|-------------|
| **FSDB path(s)** | Absolute path to one or more `.fsdb` files |
| **Signal names** | Full hierarchical paths (e.g. `top_tb.dut.dut.lock2core`) |

### Optional

| Input | Description |
|-------|-------------|
| **Anchor** | Signal + edge (`0->1`, `1->0`) defining a reference event |
| **Checks** | Pluggable analysis blocks (`duty_cycle`, extensible) |
| **Expect bounds** | PASS/FAIL thresholds on check results |

### Input mode 1 — CLI (single FSDB)

```bash
python3 scripts/fsdb_analyze.py \
  --fsdb /path/to/inter.fsdb \
  --signals top_tb.sig_a,top_tb.sig_b \
  --anchor top_tb.dut.dut.lock2core \
  --edge 0->1 \
  -o report.txt
```

CLI duty-cycle flags:

```bash
  --duty-cycle              enable duty_cycle check
  --duty-signals SIG1,SIG2  signals to measure (default: --signals)
  --duty-cycles 10          periods to average (default 10)
  --duty-min 45 --duty-max 55   optional PASS/FAIL bounds
```

### Input mode 2 — JSON config (single or multi-FSDB)

Copy a template from `config/` and edit:

```bash
cp config/duty_cycle.example.json my_analysis.json
# Edit runs[].fsdb, signals, checks, anchor
python3 scripts/fsdb_analyze.py -c my_analysis.json -o report.txt
```

**Minimal config shape:**

```json
{
  "runs": [
    {
      "id": "seed_123",
      "label": "my_test",
      "fsdb": "/absolute/path/to/inter.fsdb",
      "signals": ["top_tb.dut.signal_a"],
      "anchor": {
        "signal": "top_tb.dut.lock2core",
        "edge": "0->1"
      }
    }
  ]
}
```

**Multi-FSDB:** add more entries to `runs[]`. Top-level `signals`, `anchor`, and `checks` apply to all runs unless overridden per run.

Full schema: [config.schema.md](config.schema.md)

### Finding correct signal paths

If a signal is `NOT_FOUND`, search the FSDB hierarchy:

```bash
fsdbdebug -hier_tree /path/to/inter.fsdb 2>&1 | grep "my_signal_name"
```

Use the exact scope from the `Var: vcd_wire` / `Var: vcd_reg` line.

---

## Output

### Report file

Plain text, one section per FSDB run. Written to stdout or `-o report.txt`.

### Per-run sections

**1. Header** — run id, label, FSDB path, time scale

**2. Anchor** (if set)

```
Anchor: top_tb.dut.dut.lock2core
  Edge: 0->1
  Status: edge 0->1 @ 169615.000 ns
  Anchor timeline:
    @        0.000 ns  = 0
    @   169615.000 ns  = 1
```

**3. Signals table**

```
Signal                                               Before    After    Final    #VC
------------------------------------------------------------------------------------
top_tb.dut.dut.xbf.xiopll_custom.xdca0.clkout             0   toggle        0    407
```

| Column | Meaning |
|--------|---------|
| Before | Stable value just before anchor edge |
| After | Stable value after anchor (+ offset), or `toggle` if many edges |
| Final | Last value in simulation |
| #VC | Number of value changes (activity indicator) |

**4. Checks section** (if `checks[]` configured)

```
Check: dca_clkout_calibrated (duty_cycle) — clkout duty (calibrated — expect ~50%)
  Status: ok
  Anchor: top_tb.dut.dut.lock2core  edge=0->1
  Anchor time: 169615.000 ns

    Signal                                             Duty%     Period       High       Freq     Cy    Exp
    -------------------------------------------------------------------------------------------------------
    top_tb.dut.dut.xbf.xiopll_custom.xdca0.clkout     50.00%  1280.000ns   640.000ns    0.7812M     10   PASS
```

| Column | Meaning |
|--------|---------|
| Duty% | Average high-time / period over N cycles |
| Period / High | Average period and high pulse width (ns) |
| Freq | Implied frequency (MHz) |
| Cy | Cycles measured |
| Exp | PASS / FAIL / — (dash = no expect bounds) |

### Exit codes

- `0` — completed (individual checks may show FAIL in report)
- Non-zero — config error, missing FSDB, or script failure

---

## Usage examples

### Example 1 — Signal levels before/after lock (single FSDB)

```bash
python3 scripts/fsdb_analyze.py \
  --fsdb /path/to/seed/inter.fsdb \
  --signals top_tb.dut.dut.xbf.xfpll_ctrl.dsm_lock,top_tb.dut.dut.xbf.xfpll_ctrl.pfd_lockrstb \
  --anchor top_tb.dut.dut.xbf.xfpll_ctrl.dsm_lock \
  --edge 0->1 \
  -o report.txt
```

### Example 2 — Duty cycle after lock2core (CLI)

```bash
python3 scripts/fsdb_analyze.py \
  --fsdb /path/to/seed/inter.fsdb \
  --signals top_tb.dut.dut.xbf.xiopll_custom.xdca0.clkout \
  --anchor top_tb.dut.dut.lock2core \
  --duty-cycle --duty-cycles 10 --duty-min 45 --duty-max 55 \
  -o report.txt
```

### Example 3 — Batch regression (multi-FSDB config)

```bash
python3 scripts/fsdb_analyze.py \
  -c config/duty_cycle.example.json \
  -o regression_duty_report.txt
```

Edit `config/duty_cycle.example.json` first — set real FSDB paths under `runs[]`.

### Example 4 — Raw VC dump (debug)

```bash
python3 scripts/fsdb_analyze.py \
  -c my_analysis.json \
  --dump-only \
  -o ./vc_out
```

Writes `run_<id>_vc.txt` per FSDB with raw value-change lines.

---

## Modular checks

Checks are defined in `checks[]` and dispatched by `scripts/fsdb_checks.py`. Each check is independent: its own anchor, signals, parameters, and optional expect bounds.

```json
{
  "checks": [
    {
      "type": "duty_cycle",
      "id": "my_check",
      "label": "Human-readable description",
      "anchor": { "signal": "top_tb.anchor_sig", "edge": "0->1" },
      "signals": ["top_tb.clk_out"],
      "params": { "cycles": 10, "start_offset_fs": 0 },
      "expect": { "duty_pct_min": 45.0, "duty_pct_max": 55.0 }
    }
  ]
}
```

| Scope | Behavior |
|-------|----------|
| Top-level `checks[]` | Applied to **every** run |
| `runs[].checks[]` | **Appended** for that run only (different anchor per design) |
| Omitted `anchor` / `signals` in check | Inherited from run or top-level config |

### Available check types

| Type | Description |
|------|-------------|
| `duty_cycle` | Average duty %, period, frequency over N cycles after anchor |

To add a new type: see [IMPROVING.md](IMPROVING.md).

### Design note — xdca duty calibration (GPPLL / DCC)

The `xdca` module calibrates duty to 50% on **`clkout`**. **`clkin`** may have distorted duty — that is expected.

Use **two checks**:

- `clkin` — report only (no `expect`)
- `clkout` — `expect` 45–55%

See [examples/km_gppll.md](examples/km_gppll.md) and [config/duty_cycle.example.json](config/duty_cycle.example.json).

---

## Sharing with colleagues

### Create a tarball

```bash
cd ~/.cursor/skills
tar czvf analyze-fsdb-verdi.tar.gz analyze-fsdb-verdi/
```

### Colleague install

```bash
mkdir -p ~/.cursor/skills
cd ~/.cursor/skills
tar xzvf /path/to/analyze-fsdb-verdi.tar.gz
```

### Via git (project or shared repo)

```bash
git clone <repo-url> ~/.cursor/skills/analyze-fsdb-verdi
```

### What colleagues need

1. This README
2. Run `python3 scripts/fsdb_env.py` — fix anything marked NOT READY
3. (Optional) `config/env.local.json` from `env.example.json` for non-default paths
4. A copied analysis config template with their FSDB paths
5. (Optional) Cursor for agent-assisted analysis

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Preflight NOT READY | `fsdbdebug` not on host PATH | Run `fsdb_env.py`; use ARC shell or `env.local.json` |
| `Signal NOT_FOUND` | Wrong hierarchy path | `fsdbdebug -hier_tree FSDB \| grep signal_name` |
| `anchor not found or no VC` | Signal not dumped to FSDB | Check `novas_dump.log` dump scope |
| `no 0->1 on anchor` | Edge never occurred | Try different edge or anchor signal |
| Empty / missing VC | vidcode from wrong FSDB | Script resolves per file — do not hardcode vidcodes |
| Arc shell permission denied | Environment restriction | Try `fsdbdebug` directly; or run on a DV machine |
| Duty FAIL at lock boundary | Startup transient | Increase `start_offset_fs` in check params |
| `clkin` duty not 50% | Expected (xdca input) | Apply `expect` on `clkout` only |

---

## Further reading

| Document | Contents |
|----------|----------|
| [config.schema.md](config.schema.md) | Full JSON config reference |
| [reference.md](reference.md) | fsdbdebug commands, VC parsing, arc shell |
| [examples/km_gppll.md](examples/km_gppll.md) | GPPLL/DCC signal names, anchors, xdca notes |
| [IMPROVING.md](IMPROVING.md) | Adding new check types |
| [SKILL.md](SKILL.md) | Cursor agent trigger text and workflow |

---

## Quick reference

```bash
# Install
cp -r analyze-fsdb-verdi ~/.cursor/skills/

# Verify dependencies
python3 ~/.cursor/skills/analyze-fsdb-verdi/scripts/fsdb_env.py

# Run (config)
python3 ~/.cursor/skills/analyze-fsdb-verdi/scripts/fsdb_analyze.py \
  -c my_analysis.json -o report.txt

# Run (CLI)
python3 ~/.cursor/skills/analyze-fsdb-verdi/scripts/fsdb_analyze.py \
  --fsdb /path/to/inter.fsdb \
  --signals top_tb.sig_a \
  --anchor top_tb.lock --edge 0->1 \
  --duty-cycle -o report.txt
```
