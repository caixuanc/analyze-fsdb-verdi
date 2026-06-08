# FSDB analysis reference

## Arc / workset pattern

Typical workset first line:

```
/p/psg/ctools/arc/2019.1/bin/arc shell --no-inherit km_dv/2025WW48 synopsys_vcsmx/V-2023.12 synopsys_verdi/V-2023.12 $*; exit
```

Wrap all EDA commands:

```bash
/p/psg/ctools/arc/2019.1/bin/arc shell --no-inherit km_dv/2025WW48 synopsys_verdi/V-2023.12 -- bash script.sh
```

## fsdbdebug command cheat sheet

```bash
# File info
fsdbdebug -info inter.fsdb

# Full hierarchy (large)
fsdbdebug -hier_tree inter.fsdb > hier.txt

# Value changes for one signal
fsdbdebug -vc -vidcode <ID> inter.fsdb

# VC count only
fsdbdebug -vc_count -vidcode <ID> inter.fsdb
```

### Parsing `Var:` lines

Example:

```
Var: vcd_wire top_tb.dut.dut.xbf.xfpll_ctrl.dsm_lock l:0 r:0 implicit 12510 1B 0
```

- Scope: `top_tb.dut.dut.xbf.xfpll_ctrl.dsm_lock`
- Vidcode: `12510`
- Filter out variants: `dsm_lock_la`, `dsm_lock_ovrd`, `pfd_lockrstb_dft` unless requested

### Parsing VC lines

Example:

```
2 vc: xtag: (22 3415719488)  val: 1  seq_num: 332   region :(1, Active)
```

- Value: `1`
- Time (1fs scale): `22 * 2^32 + 3415719488` fs = **97905 ns**

## Related signals (GPPLL frac / DTC)

When anchor behavior is unclear, also dump:

| Signal | Purpose |
|--------|---------|
| `xfpll_ctrl.dsm_lock` | ASIC frac mode flag (output) |
| `xfpll_ctrl.dsm_lock_override` | Mux select for lock path |
| `xfpll_ctrl.final_lock_presync` / `final_lock_presync_buf` | PLL lock before mux |
| `xfpll_ctrl.ratio_halfn` | DSM half-integer to custom |
| `xiopll_custom...igmotionwrap.gmotionhalf` | G-divider half step |
| `xfpll_ctrl.pfd_lockrstb` | PFD lock reset (active-high deassert) |

## simv.daidir locations

For regression `.../2026_MM_DD_*_frontdoor_frac_/`:

| Build | simv.daidir |
|-------|----------------|
| Non-DTC | `<rundir>/frac_regress_0/simv.daidir` |
| DTC | `<rundir>/DTC_frac_regress_0/simv.daidir` |

## novas_dump.log

Check `seed_*/novas_dump.log` for dump scope (`+all`), end time, and variable count.

## Output semantics

| Report | Meaning |
|--------|---------|
| `0` / `1` | Stable logic level in that window |
| `toggle (0/1)` | Many transitions after anchor (DSM) |
| `N/A (no anchor=0 window)` | Anchor never 0 after reset (common DTC) |
| `held` | No VC after initial assignment |
