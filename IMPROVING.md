# Improving analyze-fsdb-verdi

## Add a new check type (recommended pattern)

1. Implement core logic in `scripts/fsdb_lib.py` (pure functions on VC data).
2. Add handler in `scripts/fsdb_checks.py`:
   - Register in `CHECK_HANDLERS` dict
   - Add default params to `DEFAULT_PARAMS` if needed
   - Implement `run_<type>_check(check, raw, scale_fs, defaults) -> result dict`
3. Extend `format_checks_report()` for human-readable output (or add type-specific formatter).
4. Document fields in `config.schema.md` and add an example under `config/`.

Each check is self-contained: its own `anchor`, `signals`, `params`, and optional `expect`.

## Add project defaults

- Put a checked-in config under your repo: `scripts/fsdb/my_regress.json`
- Reference it from a Cursor rule or project `AGENTS.md`

## Corner cases to capture

- Anchor never transitions → check reports error; before/after use full waveform bounds
- Constant signal (2 VCs at t=0) → duty cycle reports `insufficient_cycles`
- Shared FSDB across cases → duplicate paths in config, different labels
- Different designs / anchors → use per-run `checks[]` overrides

## Testing

```bash
python3 fsdb_analyze.py -c config/single.example.json
python3 fsdb_analyze.py -c config/duty_cycle.example.json -o /tmp/report.txt
python3 fsdb_analyze.py --fsdb /path/to/inter.fsdb \
  --signals top.a,top.b --anchor top.lock --duty-cycle \
  --duty-signals top.a -o /tmp/report.txt
```

Validate on a real `inter.fsdb` before committing config to CI.
