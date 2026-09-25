# FSDB analysis config schema

JSON config drives `scripts/fsdb_analyze.py`. One file can describe **one or many** FSDB runs.

## Top-level fields

| Field | Required | Description |
|-------|----------|-------------|
| `runs` | yes* | List of per-FSDB runs (alias: `fsdbs`) |
| `signals` | no | Default probe list for all runs |
| `anchor` | no | Default anchor for all runs |
| `fsdbdebug` | no | Path to `fsdbdebug` binary (auto-detected if omitted) |

## Site environment (`config/env.local.json`)

Optional per-user / per-site file (copy from `config/env.example.json`). Not part of analysis JSON; loaded automatically by preflight.

| Field | Description |
|-------|-------------|
| `fsdbdebug` | Override default `fsdbdebug` path |
| `arc_bin` | Path to `arc` binary |
| `arc_verdi_resource` | e.g. `synopsys_verdi/V-2023.12` for `arc resource-use` |
| `arc_worksets` | List of worksets for recommended `arc shell` command |
| `anchor_defaults` | no | Default edge, offsets, toggle threshold |

\* Or use CLI: `--fsdb` + `--signals` without a config file.

## Run object

| Field | Required | Description |
|-------|----------|-------------|
| `id` | recommended | Short id (report header, dump filenames) |
| `label` | no | Human description |
| `fsdb` | yes | Path to `.fsdb` file |
| `signals` | yes** | Hierarchical signal names to analyze |
| `anchor` | no | Override top-level anchor for this run |

** Inherited from top-level `signals` if omitted.

## Anchor object

| Field | Default | Description |
|-------|---------|-------------|
| `signal` | — | Hierarchical anchor signal |
| `edge` | `0->1` | Transition to detect (`0->1`, `1->0`, …) |
| `before_offset_fs` | `1000` | Sample “before” at `t_edge - offset` |
| `after_offset_fs` | `1000000000` | Sample “after” at `t_edge + offset` (1 µs @ 1fs scale) |

## Behavior modes

1. **With anchor** — For each probe: stable value before edge, value/toggle after edge.
2. **Without anchor** — Report initial/final level and VC count; short timeline if few transitions.
3. **Checks** — Pluggable analysis blocks (`checks[]`) with their own anchor/signals/params.

## Checks (modular)

Top-level `checks` apply to **every** run. Each run may add more via `runs[].checks` (appended).

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | Check handler name (e.g. `duty_cycle`) |
| `id` | recommended | Short id for report |
| `label` | no | Human description |
| `anchor` | yes* | Anchor for this check (`signal`, `edge`) |
| `signals` | yes* | Signals to analyze |
| `params` | no | Type-specific parameters |
| `expect` | no | Optional PASS/FAIL bounds |

\* Inherited from run-level or top-level `anchor` / `signals` when omitted.

### duty_cycle params

| Field | Default | Description |
|-------|---------|-------------|
| `cycles` | `10` | Number of complete periods to average |
| `start_offset_fs` | `0` | Delay after anchor edge before measuring |

### duty_cycle expect

| Field | Description |
|-------|-------------|
| `duty_pct_min` | Fail if average duty % below this |
| `duty_pct_max` | Fail if average duty % above this |
| `period_ns_min` | Fail if average period below this |
| `period_ns_max` | Fail if average period above this |

## Examples

See `config/example.json`, `config/duty_cycle.example.json`, `config/multi_check.example.json`.
