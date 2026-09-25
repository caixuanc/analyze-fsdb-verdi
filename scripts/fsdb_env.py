#!/usr/bin/env python3
"""Environment detection and preflight checks for analyze-fsdb-verdi."""
from __future__ import print_function

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_FSDBDEBUG = (
    "/p/psg/eda/synopsys/verdi/V-2023.12/linux64/suse/bin/fsdbdebug"
)
DEFAULT_ARC_BIN = "/p/psg/ctools/arc/2019.1/bin/arc"
DEFAULT_ARC_VERDI = "synopsys_verdi/V-2023.12"
DEFAULT_ARC_WORKSETS = ["km_dv/2025WW48"]

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_SITE_CONFIG_NAMES = ("env.local.json", "env.json")


def _skill_config_paths():
    config_dir = _SKILL_ROOT / "config"
    for name in _SITE_CONFIG_NAMES:
        path = config_dir / name
        if path.is_file():
            yield path


def load_site_config():
    """Merge site config files (env.local.json overrides env.json)."""
    merged = {}
    for path in reversed(list(_skill_config_paths())):
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged.update(data)
        except (IOError, ValueError):
            continue
    return merged


def resolve_arc_bin(explicit=None):
    if explicit:
        return explicit
    site = load_site_config()
    if site.get("arc_bin"):
        return site["arc_bin"]
    found = shutil.which("arc")
    if found:
        return found
    if os.path.isfile(DEFAULT_ARC_BIN) and os.access(DEFAULT_ARC_BIN, os.X_OK):
        return DEFAULT_ARC_BIN
    return None


def _is_executable(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def _parse_arc_resource_use(output):
    """Extract VERDI_HOME and PATH entries from arc resource-use output."""
    env = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    paths = []
    verdi_home = env.get("VERDI_HOME") or env.get("NOVAS_HOME")
    if verdi_home:
        paths.append(os.path.join(verdi_home, "bin", "fsdbdebug"))
        paths.append(os.path.join(verdi_home, "suse", "bin", "fsdbdebug"))
    path_val = env.get("PATH", "")
    for entry in path_val.split(":"):
        if not entry:
            continue
        paths.append(os.path.join(entry, "fsdbdebug"))
    return paths


def discover_fsdbdebug_via_arc(arc_bin, verdi_resource=None):
    """Try arc resource-use to locate fsdbdebug."""
    if not arc_bin or not _is_executable(arc_bin):
        return []
    site = load_site_config()
    resource = verdi_resource or site.get("arc_verdi_resource") or DEFAULT_ARC_VERDI
    try:
        proc = subprocess.run(
            [arc_bin, "resource-use", resource],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    found = []
    for candidate in _parse_arc_resource_use(proc.stdout):
        if _is_executable(candidate):
            found.append((candidate, "arc:{}".format(resource)))
    return found


def discover_fsdbdebug_candidates():
    """Return ordered (path, source) candidates without picking a winner."""
    site = load_site_config()
    candidates = []

    def add(path, source):
        if path and (path, source) not in candidates:
            candidates.append((path, source))

    env_path = os.environ.get("FSDBDEBUG")
    if env_path:
        add(env_path, "FSDBDEBUG")

    if site.get("fsdbdebug"):
        add(site["fsdbdebug"], "config:{}".format(site.get("_config_path", "env.json")))

    add(DEFAULT_FSDBDEBUG, "default")

    which_path = shutil.which("fsdbdebug")
    if which_path:
        add(which_path, "PATH")

    arc_bin = resolve_arc_bin()
    for path, source in discover_fsdbdebug_via_arc(arc_bin):
        add(path, source)

    return candidates


def resolve_fsdbdebug(explicit=None):
    """
    Pick the best available fsdbdebug binary.

    Priority: explicit arg > $FSDBDEBUG > site config > default path >
    PATH > arc resource-use discovery.
    """
    if explicit:
        return explicit, "explicit"

    for path, source in discover_fsdbdebug_candidates():
        if _is_executable(path):
            return path, source

    # Return best guess for error reporting even if not executable.
    for path, source in discover_fsdbdebug_candidates():
        return path, source
    return DEFAULT_FSDBDEBUG, "default"


def test_fsdbdebug(fsdbdebug, fsdb=None):
    """Verify fsdbdebug runs; optionally probe an FSDB with -info."""
    result = {
        "ok": False,
        "path": fsdbdebug,
        "version": None,
        "error": None,
    }
    if not _is_executable(fsdbdebug):
        result["error"] = "binary not found or not executable"
        return result

    try:
        proc = subprocess.run(
            [fsdbdebug],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
        return result

    out = proc.stdout or ""
    m = re.search(r"Version\s+(\S+)", out)
    if m:
        result["version"] = m.group(1)
    elif "fsdbdebug" in out.lower():
        result["version"] = "unknown"
    else:
        result["error"] = "unexpected fsdbdebug output"
        return result

    if fsdb:
        if not os.path.isfile(fsdb):
            result["error"] = "FSDB file not found: {}".format(fsdb)
            return result
        try:
            info_proc = subprocess.run(
                [fsdbdebug, "-info", fsdb],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["error"] = "fsdbdebug -info failed: {}".format(exc)
            return result
        info_out = info_proc.stdout or ""
        if info_proc.returncode != 0 and "scale unit" not in info_out.lower():
            result["error"] = "fsdbdebug -info failed (exit {})".format(
                info_proc.returncode)
            return result
        scale_m = re.search(r"scale unit\s*:\s*(\d+)\s*fs", info_out, re.I)
        if scale_m:
            result["fsdb_scale_fs"] = int(scale_m.group(1))

    result["ok"] = True
    return result


def discover_arc_verdi_versions(arc_bin):
    if not arc_bin or not _is_executable(arc_bin):
        return []
    try:
        proc = subprocess.run(
            [arc_bin, "resource-list", "synopsys_verdi"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    versions = []
    for line in proc.stdout.splitlines():
        m = re.match(r"\s+(V-[\d.]+|J-[\d.-]+|K-[\d.-]+|L-[\d.-]+|M-[\d.-]+|"
                     r"\d{4}\.\d{2}(?:-[\w-]+)?)\s+id=", line)
        if m:
            versions.append(m.group(1))
    return versions


def build_arc_shell_cmd(arc_bin=None, worksets=None, verdi_resource=None):
    site = load_site_config()
    arc_bin = arc_bin or resolve_arc_bin() or DEFAULT_ARC_BIN
    worksets = worksets or site.get("arc_worksets") or DEFAULT_ARC_WORKSETS
    verdi_resource = (
        verdi_resource or site.get("arc_verdi_resource") or DEFAULT_ARC_VERDI
    )
    parts = [arc_bin, "shell", "--no-inherit"] + list(worksets) + [verdi_resource, "--"]
    return " ".join(parts)


def run_preflight(fsdbdebug=None, fsdb=None, skip_arc=False):
    """Run all dependency checks. Returns a structured result dict."""
    site = load_site_config()
    resolved_path, resolved_source = resolve_fsdbdebug(explicit=fsdbdebug)
    fsdb_test = test_fsdbdebug(resolved_path, fsdb=fsdb)

    arc_bin = resolve_arc_bin()
    arc_info = {
        "ok": bool(arc_bin and _is_executable(arc_bin)),
        "path": arc_bin,
        "verdi_versions": [],
        "recommended_shell": None,
        "needed": not fsdb_test["ok"],
    }
    if not skip_arc and arc_info["ok"]:
        arc_info["verdi_versions"] = discover_arc_verdi_versions(arc_bin)
        arc_info["recommended_shell"] = build_arc_shell_cmd(arc_bin)

    python_info = {
        "ok": sys.version_info >= (3, 6),
        "version": "{}.{}.{}".format(
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        ),
    }

    fsdb_info = None
    if fsdb:
        fsdb_info = {
            "path": fsdb,
            "ok": os.path.isfile(fsdb),
            "readable": os.path.isfile(fsdb) and os.access(fsdb, os.R_OK),
        }
        if fsdb_test.get("fsdb_scale_fs") is not None:
            fsdb_info["scale_fs"] = fsdb_test["fsdb_scale_fs"]

    suggestions = []
    if not fsdb_test["ok"]:
        if arc_info["ok"]:
            suggestions.append(
                "Run inside ARC shell: {}".format(arc_info["recommended_shell"])
            )
            suggestions.append(
                "Or set FSDBDEBUG after: eval $(arc resource-use {})".format(
                    site.get("arc_verdi_resource") or DEFAULT_ARC_VERDI
                )
            )
        else:
            suggestions.append(
                "Install or expose fsdbdebug on PATH, or set FSDBDEBUG"
            )
        suggestions.append(
            "Copy config/env.example.json to config/env.local.json and "
            "set fsdbdebug / arc_verdi_resource for your site"
        )
        for path, source in discover_fsdbdebug_candidates():
            if path != resolved_path:
                suggestions.append("Tried {} ({})".format(path, source))

    ok = python_info["ok"] and fsdb_test["ok"]
    if fsdb_info is not None:
        ok = ok and fsdb_info["ok"] and fsdb_info["readable"]

    return {
        "ok": ok,
        "python": python_info,
        "fsdbdebug": {
            "ok": fsdb_test["ok"],
            "path": resolved_path,
            "source": resolved_source,
            "version": fsdb_test.get("version"),
            "error": fsdb_test.get("error"),
        },
        "arc": arc_info,
        "fsdb": fsdb_info,
        "site_config": {
            "loaded": bool(site),
            "paths": [str(p) for p in _skill_config_paths()],
        },
        "suggestions": suggestions,
    }


def format_preflight_report(result):
    lines = []
    sep = "=" * 72
    lines.append(sep)
    lines.append("FSDB ANALYZER PREFLIGHT")
    lines.append(sep)
    lines.append("")

    status = "READY" if result["ok"] else "NOT READY"
    lines.append("Overall: {}".format(status))
    lines.append("")

    py = result["python"]
    lines.append("[{}] Python {}".format("OK" if py["ok"] else "FAIL", py["version"]))

    fd = result["fsdbdebug"]
    fd_tag = "OK" if fd["ok"] else "FAIL"
    lines.append("[{}] fsdbdebug".format(fd_tag))
    lines.append("  path:   {}".format(fd["path"]))
    lines.append("  source: {}".format(fd["source"]))
    if fd.get("version"):
        lines.append("  version: {}".format(fd["version"]))
    if fd.get("error"):
        lines.append("  error:  {}".format(fd["error"]))

    arc = result["arc"]
    if arc["path"]:
        arc_tag = "OK" if arc["ok"] else "FAIL"
        lines.append("[{}] ARC ({})".format(arc_tag, arc["path"]))
        if arc.get("recommended_shell"):
            lines.append("  shell:  {}".format(arc["recommended_shell"]))
        if arc.get("verdi_versions"):
            preview = ", ".join(arc["verdi_versions"][:5])
            if len(arc["verdi_versions"]) > 5:
                preview += ", ..."
            lines.append("  verdi:  {} version(s) listed ({})".format(
                len(arc["verdi_versions"]), preview))
        if arc.get("needed"):
            lines.append("  note:   ARC shell may be required on this host")
    else:
        lines.append("[--] ARC not found (optional if fsdbdebug works directly)")

    fsdb = result.get("fsdb")
    if fsdb:
        fs_tag = "OK" if fsdb["ok"] and fsdb["readable"] else "FAIL"
        lines.append("[{}] FSDB".format(fs_tag))
        lines.append("  path: {}".format(fsdb["path"]))
        if fsdb.get("scale_fs") is not None:
            lines.append("  scale: {} fs per unit".format(fsdb["scale_fs"]))

    sc = result.get("site_config", {})
    if sc.get("paths"):
        lines.append("")
        lines.append("Site config: {}".format(", ".join(sc["paths"])))

    if result.get("suggestions"):
        lines.append("")
        lines.append("Suggestions:")
        for item in result["suggestions"]:
            lines.append("  - {}".format(item))

    lines.append("")
    lines.append(sep)
    return "\n".join(lines)


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Preflight check for analyze-fsdb-verdi dependencies")
    ap.add_argument("--fsdbdebug", default=None, help="Override fsdbdebug path")
    ap.add_argument("--fsdb", default=None, help="Optional FSDB to probe with -info")
    ap.add_argument("--skip-arc", action="store_true",
                    help="Skip ARC discovery (faster)")
    ap.add_argument("--json", action="store_true", help="Emit JSON result")
    args = ap.parse_args()

    result = run_preflight(
        fsdbdebug=args.fsdbdebug,
        fsdb=args.fsdb,
        skip_arc=args.skip_arc,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_preflight_report(result))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
