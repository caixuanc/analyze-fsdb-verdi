#!/bin/bash
# Legacy: dump FSDB value changes from cases.txt (pipe format).
# Prefer: python3 fsdb_analyze.py -c config.json --dump-only -o out_dir
#
# Usage (inside arc shell with synopsys_verdi):
#   dump_fsdb_vc.sh cases.txt [out_dir]
#
# cases.txt format:
#   case_id|fsdb_path|anchor_signal|probe_sig1;probe_sig2;...

set -euo pipefail

CASES="${1:?cases file required}"
OUTDIR="${2:-./fsdb_analysis_out}"
FSDBDEBUG="${FSDBDEBUG:-/p/psg/eda/synopsys/verdi/V-2023.12/linux64/suse/bin/fsdbdebug}"

mkdir -p "$OUTDIR"

lookup_vid() {
  local fsdb=$1 sig=$2
  local hier
  hier=$(mktemp)
  $FSDBDEBUG -hier_tree "$fsdb" 2>/dev/null >"$hier" || true
  # Match end of scope path (space after signal name)
  grep -F "${sig} " "$hier" | grep "Var: vcd" | head -1 | sed -n 's/.* \([0-9][0-9]*\) 1B.*/\1/p'
  rm -f "$hier"
}

while IFS='|' read -r cid fsdb anchor probes || [[ -n "${cid:-}" ]]; do
  [[ -z "${cid:-}" || "$cid" =~ ^# ]] && continue
  [[ ! -f "$fsdb" ]] && echo "CASE $cid: MISSING $fsdb" >&2 && continue

  out="$OUTDIR/case${cid}_vc.txt"
  echo "CASE $cid" >"$out"
  echo "FSDB: $fsdb" >>"$out"
  echo "anchor: $anchor" >>"$out"

  IFS=';' read -ra sigs <<< "$probes"
  for s in "${sigs[@]}"; do
    [[ -z "$s" ]] && continue
    vid=$(lookup_vid "$fsdb" "$s")
    if [[ -z "$vid" ]]; then
      echo "" >>"$out"
      echo "=== $s === VID NOT FOUND" >>"$out"
      continue
    fi
    echo "" >>"$out"
    echo "=== $s (vid=$vid) ===" >>"$out"
    $FSDBDEBUG -vc -vidcode "$vid" "$fsdb" 2>&1 | grep "^[0-9]* vc:" >>"$out" || true
  done

  # anchor last (for parse script)
  avid=$(lookup_vid "$fsdb" "$anchor")
  echo "" >>"$out"
  echo "=== ANCHOR $anchor (vid=$avid) ===" >>"$out"
  if [[ -n "$avid" ]]; then
    $FSDBDEBUG -vc -vidcode "$avid" "$fsdb" 2>&1 | grep "^[0-9]* vc:" >>"$out" || true
  fi

  echo "Wrote $out"
done <"$CASES"
