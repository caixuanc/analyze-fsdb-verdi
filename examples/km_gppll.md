# Example: km_gppll fractional / DTC FSDB checks

Optional domain notes for Intel GPPLL regressions. The core tool is generic; only paths and signal names differ per project.

## Typical signals

| Name | Hierarchy (suffix) |
|------|-------------------|
| dsm_lock | `...xfpll_ctrl.dsm_lock` |
| pfd_lockrstb | `...xfpll_ctrl.pfd_lockrstb` |
| gmotionhalf | `...xmmd.igmotionwrap.gmotionhalf` |

## Path pitfalls

- Rundir may end with `_` (e.g. `..._frontdoor_frac_/`)
- Test dirs may use `__` (e.g. `km_gppll_pwr_up__GP0_1_test`)
- DTC: `DTC_frac_regress_0/` vs `frac_regress_0/`

## DTC (`cr_dtcen=1`)

- `dsm_lock` may be **1** from t≈0; use `final_lock_presync_buf` **0→1** as anchor if needed.
- `gmotionhalf` / `pfd_lockrstb` often stay **0** when DTC forces `ratio_halfn=0`.

## Fractional (non-DTC)

- Anchor: `dsm_lock` **0→1** at PLL lock (~90–130 µs).
- `gmotionhalf` may **toggle** after lock — report shows `toggle` in After column.

## Sample config snippet

```json
{
  "signals": [
    "top_tb.dut.dut.xbf.xfpll_ctrl.pfd_lockrstb",
    "top_tb.dut.dut.xbf.xiopll_custom.xiopll_core.xmmd.igmotionwrap.gmotionhalf"
  ],
  "anchor": {
    "signal": "top_tb.dut.dut.xbf.xfpll_ctrl.dsm_lock",
    "edge": "0->1"
  },
  "runs": [
    { "id": "1", "label": "kfrac=0", "fsdb": "/path/to/seed/inter.fsdb" }
  ]
}
```

For DTC runs, override per run:

```json
"anchor": {
  "signal": "top_tb....final_lock_presync_buf",
  "edge": "0->1"
}
```

## Duty cycle after lock2core (DCC / xdca)

Signal paths include `.xbf.` scope.

**xdca design context:** `xdca` performs duty-cycle calibration to 50%. `clkin` may
have distorted duty (non-50%) — that is expected. The calibrated output is `clkout`;
apply PASS/FAIL `expect` on **clkout only**. Report `clkin` duty for visibility
without bounds.

```json
{
  "checks": [
    {
      "type": "duty_cycle",
      "id": "dca_clkin_report",
      "label": "clkin duty (informational)",
      "anchor": { "signal": "top_tb.dut.dut.lock2core", "edge": "0->1" },
      "signals": [
        "top_tb.dut.dut.xbf.xiopll_custom.xdca0.clkin",
        "top_tb.dut.dut.xbf.xiopll_custom.xdca1.clkin"
      ],
      "params": { "cycles": 10 }
    },
    {
      "type": "duty_cycle",
      "id": "dca_clkout_calibrated",
      "label": "clkout duty (calibrated — expect ~50%)",
      "anchor": { "signal": "top_tb.dut.dut.lock2core", "edge": "0->1" },
      "signals": [
        "top_tb.dut.dut.xbf.xiopll_custom.xdca0.clkout",
        "top_tb.dut.dut.xbf.xiopll_custom.xdca1.clkout"
      ],
      "params": { "cycles": 10 },
      "expect": { "duty_pct_min": 45.0, "duty_pct_max": 55.0 }
    }
  ]
}
```

Full example: [config/duty_cycle.example.json](../config/duty_cycle.example.json)
