#!/usr/bin/env python3
"""Component metadata inventory (F-01.2).

    python -I composition/inventory/metadata_inventory.py --resolved <resolver --work dir> [--out composition/inventory/component-inventory.json]

Derives a per-package inventory (name, version, ecosystem, declared licence, digest
source) from the lock, the npm package-lock.json `license` fields, `pip inspect --path`
of the resolver's installed host tree (installer metadata: License-Expression, License,
Classifier) and, for Python packages present only in non-host targets, the PyPI JSON
API. This is a METADATA INVENTORY: declared licences as published, not an SBOM and not
a licence-compliance verification. No installed package is imported or executed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _no_window():
    """integrations/platform/no_window.py, the shared no-window helper, loaded by path once per process:
    ``_no_window().no_window_flags()`` is CREATE_NO_WINDOW only where this process has no console."""
    module = sys.modules.get('aieh_no_window')
    if module is None:
        spec = importlib.util.spec_from_file_location(
            'aieh_no_window', HERE.parents[1] / 'integrations' / 'platform' / 'no_window.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['aieh_no_window'] = module
    return module
LOCK_DIR = HERE.parent / "lock"


def norm(n):
    return re.sub(r"[-_.]+", "-", n).lower()


def req_pins(path):
    return {norm(m.group(1)): m.group(2) for m in re.finditer(r"^([A-Za-z0-9._-]+)==(\S+)", path.read_text(encoding="utf-8"), re.M)}


def py_license(meta):
    expr = meta.get("license_expression")
    lic = (meta.get("license") or "").strip()
    cls = [c.split(" :: ")[-1] for c in meta.get("classifier", []) if c.startswith("License ::")]
    if expr:
        return expr, "License-Expression"
    if lic and len(lic) < 120 and "\n" not in lic:
        return lic, "License"
    if cls:
        return "; ".join(cls), "Classifier"
    if lic:
        return "(full licence text in License field)", "License"
    return None, "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolved", required=True)
    ap.add_argument("--out", default=str(HERE / "component-inventory.json"))
    a = ap.parse_args()
    work = Path(a.resolved).resolve()
    lock = json.loads((LOCK_DIR / "components.lock.json").read_text(encoding="utf-8"))
    items = []
    # Python
    targets = {t: req_pins(LOCK_DIR / s["file"]) for t, s in lock["python"]["platforms"].items()}
    p = subprocess.run([sys.executable, "-I", "-X", "utf8", "-m", "pip", "inspect", "--isolated", "--disable-pip-version-check",
                        "--path", str(work / "python" / "site")], capture_output=True, text=True, encoding="utf-8", check=True,
                       creationflags=_no_window().no_window_flags())
    inst = {norm(d["metadata"]["name"]): d["metadata"] for d in json.loads(p.stdout)["installed"]}
    names = sorted(set().union(*targets.values()))
    for n in names:
        ver = next(t[n] for t in targets.values() if n in t)
        if n in inst:
            lic, src = py_license(inst[n])
            src = "pip inspect (installed METADATA): " + src
        else:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{n}/{ver}/json", timeout=60) as r:
                info = json.load(r)["info"]
            lic, src = py_license({"license_expression": info.get("license_expression"), "license": info.get("license"),
                                   "classifier": info.get("classifiers", [])})
            src = "PyPI JSON (not installed on host): " + src
        items.append({"ecosystem": "pypi", "name": n, "version": ver, "targets": sorted(t for t, v in targets.items() if n in v),
                      "license_declared": lic, "license_source": src, "digest": "sha256 (hash-locked per target file)"})
    for e in lock["python"].get("reviewed_sdists", []):
        n = norm(e["name"])
        lic, src = py_license(inst[n]) if n in inst else (e.get("license"), "lock")
        items.append({"ecosystem": "pypi", "name": n, "version": e["version"], "targets": e.get("applies_to_targets", []),
                      "status": "reviewed sdist, built to a pure-Python wheel and installed (decision 0002)",
                      "license_declared": lic, "license_source": ("pip inspect (installed METADATA): " + src) if n in inst else src,
                      "digest": "sdist sha256:" + e["sha256"]})
    for e in lock["python"].get("coupled_pins", []):
        items.append({"ecosystem": "pypi", "name": e["name"], "version": e["version"], "targets": [], "status": "coupled_pins",
                      "license_declared": e.get("license", "MIT" if e["name"] == "openhands-automation" else None),
                      "license_source": "lock (F-01.1)", "digest": "sha256:" + e["sha256"]})
    # npm
    plock = json.loads((LOCK_DIR / "npm" / "package-lock.json").read_text(encoding="utf-8"))
    hidden_p = work / "npm" / "project" / "node_modules" / ".package-lock.json"
    hidden = json.loads(hidden_p.read_text(encoding="utf-8"))["packages"] if hidden_p.exists() else {}
    for path, v in sorted(plock["packages"].items()):
        if not path:
            continue
        name = path.split("node_modules/")[-1]
        items.append({"ecosystem": "npm", "name": name, "path": path, "version": v.get("version"),
                      "installed_on_host": path in hidden, "optional": bool(v.get("optional")),
                      "license_declared": v.get("license"), "license_source": "package-lock.json license (registry metadata)",
                      "digest": v.get("integrity") or "inBundle (covered by parent tarball)"})
    # OCI and release assets (component-level metadata from the lock / F-01.1)
    for o in lock["oci"]:
        items.append({"ecosystem": "oci", "name": o["repository"], "version": o["tag_at_lock_time"], "digest": o["index_digest"],
                      "license_declared": None, "license_source": "not derived: image contents not inventoried by metadata"})
    lic_counts = {}
    for it in items:
        if it["ecosystem"] in ("pypi", "npm"):
            k = it["license_declared"] or "(none declared)"
            lic_counts.setdefault(it["ecosystem"], {})
            lic_counts[it["ecosystem"]][k] = lic_counts[it["ecosystem"]].get(k, 0) + 1
    out = {"schema": "ai-engineering-harness/component-metadata-inventory", "schema_version": 1, "task": "F-01.2",
           "kind": "component metadata inventory (declared licences from lock, registries and installer metadata). NOT an SBOM; NOT a licence-compliance verification.",
           "counts": {e: sum(1 for i in items if i["ecosystem"] == e) for e in ("pypi", "npm", "oci")},
           "declared_license_counts": {e: dict(sorted(c.items(), key=lambda x: (-x[1], x[0]))) for e, c in lic_counts.items()},
           "items": items}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"counts": out["counts"], "declared_license_counts": out["declared_license_counts"]}, indent=1))


if __name__ == "__main__":
    main()
