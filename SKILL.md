---
name: analyze-fsdb-verdi
description: >-
  Modular batch FSDB analysis: user-defined signals, single or multiple FSDBs,
  human-readable reports via fsdbdebug (Synopsys Verdi). Use when the user asks
  to analyze inter.fsdb, check signal behavior, duty cycle, compare waveforms
  across runs, or mentions Verdi, fsdbdebug, arc shell, or FSDB regression paths.
---

# Analyze FSDB (modular)

Config-driven workflow: **you define FSDB path(s) and signal(s)**; the tool resolves vidcodes, dumps value changes, and prints a **readable report**.

## Prerequisites

```bash
/p/psg/ctools/arc/2019.1/bin/arc shell --no-inherit km_dv/2025WW48 synopsys_verdi/V-2023.12 -- <command>
```

Primary backend: **`fsdbdebug`** (`-hier_tree`, `-vc -vidcode`). See [reference.md](reference.md).

## Quick start

### 1. Single FSDB (CLI)

```bash
cd ~/.cursor/skills/analyze-fsdb-verdi/scripts

arc shell ... -- python3 fsdb_analyze.py \
  --fsdb /path/to/inter.fsdb \
  --signals top_tb.a,top_tb.b \
  --anchor top_tb.ctrl.lock \
  --edge 0->1 \
  --duty-cycle \
  --duty-signals top_tb.a \
  --duty-cycles 10 \
  -o report.txt
```

### 2. Multiple FSDBs or checks (config)

1. Copy [config/example.json](config/example.json) or [config/duty_cycle.example.json](config/duty_cycle.example.json) → `my_analysis.json`
2. Set `runs[].fsdb`, `signals`, optional `anchor`, optional `checks[]`
3. Run:

```bash
arc shell ... -- python3 fsdb_analyze.py -c my_analysis.json -o report.txt
```

Schema: [config.schema.md](config.schema.md)

**Modular checks:** each entry in `checks[]` has its own `type`, `anchor`, `signals`, `params`, and optional `expect` (PASS/FAIL). Top-level checks apply to all runs; `runs[].checks` adds run-specific checks (e.g. different anchor per design). See [config/multi_check.example.json](config/multi_check.example.json).

### 3. Raw VC dump only

```bash
python3 fsdb_analyze.py -c my_analysis.json --dump-only -o ./vc_out
```

## Agent workflow

```
- [ ] Confirm FSDB paths exist
- [ ] Get signal list + behavior question from user (anchor edge, duty cycle, timeline)
- [ ] Build JSON config with `checks[]` OR CLI args (`--duty-cycle`)
- [ ] Run fsdb_analyze.py (arc shell if needed; fsdbdebug may work directly)
- [ ] Deliver report.txt / stdout; explain anchor status, check PASS/FAIL, NOT_FOUND signals
```

**Do not reuse vidcodes across FSDBs** — the script resolves them per file.

## Report format

Plain-text sections per run:

- FSDB path, time scale
- Anchor: edge type, transition time (ns), full anchor timeline
- Table: each signal → Before / After (vs anchor), Final, VC count
- `toggle` = many edges after anchor (dithering clocks)
- **Checks section:** duty cycle table (Duty%, Period, Freq, Expect PASS/FAIL)

## Check types

| Type | Purpose |
|------|---------|
| `duty_cycle` | Average duty % over N periods after anchor edge |

Add new types in [scripts/fsdb_checks.py](scripts/fsdb_checks.py). See [IMPROVING.md](IMPROVING.md).

## Optional checks (no anchor)

Omit `anchor` in config to list **initial/final** levels and transition count per signal.

## Legacy scripts

| Script | Role |
|--------|------|
| [scripts/fsdb_analyze.py](scripts/fsdb_analyze.py) | **Main entry** |
| [scripts/fsdb_lib.py](scripts/fsdb_lib.py) | VC/anchor/duty-cycle library |
| [scripts/fsdb_checks.py](scripts/fsdb_checks.py) | Pluggable check registry |
| [scripts/dump_fsdb_vc.sh](scripts/dump_fsdb_vc.sh) | Old cases.txt format (still works) |
| [scripts/parse_fsdb_vc.py](scripts/parse_fsdb_vc.py) | Parse old `case*_vc.txt` dumps |

Prefer `fsdb_analyze.py` for new work.

## Project-specific notes

GPPLL / km_gppll examples (dsm_lock vs final_lock, DTC paths): [examples/km_gppll.md](examples/km_gppll.md)

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Signal NOT_FOUND | Grep `fsdbdebug -hier_tree` for exact hierarchy |
| Empty VC | Use `2>&1` with fsdbdebug; confirm vid from **this** FSDB |
| No anchor edge | Try different `edge` or another anchor signal |
| fsdbreport fails | Expected without KDB; use fsdbdebug path |

More: [reference.md](reference.md), [IMPROVING.md](IMPROVING.md)
