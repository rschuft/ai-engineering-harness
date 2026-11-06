#!/usr/bin/env python3
"""Initial SBOM / licence inventory (F-01.2).

    python -I composition/inventory/scan.py --resolved <resolver --work dir> --tools <empty dir outside the checkout>
                                            [--out composition/inventory/generated] [--skip-oci] [--only TARGET ...]

Downloads Syft and Grant from the URLs pinned in composition/lock/components.lock.json
("tools"), verifies each archive's sha256 against the lock BEFORE extracting or running
it, then:
  * syft scans the resolver's installed Python tree (<work>/python/site) and npm project
    (<work>/npm/project), and the locked OCI images by digest through Syft's registry
    source (linux/amd64 only; layers are downloaded, nothing is run);
  * grant evaluates each SBOM with Grant's own generated default configuration
    (grant-default-config.yaml, unmodified). That is NOT a project licence policy: none
    has been adopted. Its verdicts are recorded as findings, not as accept/reject.
Only Windows x86_64 tool archives are pinned (the host that produced the inventory).
No installed package is imported or executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parent.parent
LOCK = json.loads((HERE.parent / "lock" / "components.lock.json").read_text(encoding="utf-8"))


def fetch_tool(t, root: Path) -> Path:
    d = root / t["name"]
    d.mkdir(parents=True, exist_ok=False)
    archive = d / t["asset"]
    req = urllib.request.Request(t["url"], headers={"User-Agent": "ai-engineering-harness-inventory/1"})
    with urllib.request.urlopen(req, timeout=300) as r, open(archive, "wb") as f:
        shutil.copyfileobj(r, f)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != t["sha256"]:
        raise SystemExit(f"{t['name']}: sha256 {digest} != locked {t['sha256']}; refusing to run")
    bindir = d / "bin"
    with zipfile.ZipFile(archive) as z:
        z.extractall(bindir)
    exe = bindir / (t["name"] + ".exe")
    if not exe.exists():
        raise SystemExit(f"{exe} missing after extraction")
    print(f"{t['name']} {t['version']} sha256 verified {digest}")
    return exe


def run(cmd, env, cwd):
    print("  $ " + " ".join(map(str, cmd)), flush=True)
    p = subprocess.run(list(map(str, cmd)), env=env, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolved", required=True)
    ap.add_argument("--tools", required=True)
    ap.add_argument("--out", default=str(HERE / "generated"))
    ap.add_argument("--skip-oci", action="store_true")
    ap.add_argument("--only", nargs="+", help="rescan only these targets (e.g. python-host); other results in scan-manifest.json are kept")
    a = ap.parse_args()
    resolved, tools, out = Path(a.resolved).resolve(), Path(a.tools).resolve(), Path(a.out).resolve()
    if tools == CHECKOUT or CHECKOUT in tools.parents:
        raise SystemExit("--tools must be outside the checkout")
    tools.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    exes = {t["name"]: fetch_tool(t, tools) for t in LOCK["tools"] if t["name"] in ("syft", "grant")}
    tmp = tools / "tmp"
    tmp.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("SYFT_", "GRANT_", "DOCKER_", "REGISTRY_"))}
    env.update({"TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp), "SYFT_CHECK_FOR_APP_UPDATE": "false",
                "GRANT_CHECK_FOR_APP_UPDATE": "false", "XDG_CACHE_HOME": str(tools / "cache"), "XDG_CONFIG_HOME": str(tools / "config")})
    gcfg = run([exes["grant"], "config"], env, tmp)
    (out / "grant-default-config.yaml").write_text(gcfg.stdout, encoding="utf-8", newline="\n")
    # Relative targets (cwd = the resolver work dir) keep machine paths out of the SBOM documents.
    targets = [("python-host", "dir:python/site", []),
               ("npm", "dir:npm/project", [])]
    if not a.skip_oci:
        for o in LOCK["oci"]:
            slug = o["id"].split("/")[-1].replace(":", "-")
            targets.append((f"oci-{slug}", f"registry:{o['repository']}@{o['index_digest']}", ["--platform", "linux/amd64"]))
    order = [t[0] for t in targets]
    if a.only:
        targets = [t for t in targets if t[0] in a.only]
    manifest = out / "scan-manifest.json"
    previous = json.loads(manifest.read_text(encoding="utf-8"))["results"] if a.only and manifest.exists() else []
    results = [r for r in previous if r["target"] not in {t[0] for t in targets}]
    for name, src, extra in targets:
        sbom = out / f"sbom-{name}.cdx.json"
        p = run([exes["syft"], "scan", src, *extra, "-o", f"cyclonedx-json={sbom}", "-q"], env, resolved)
        rec = {"target": name, "source": src if extra else src.replace("dir:", "dir:<resolved>/"), "platform": "linux/amd64" if extra else "host",
               "syft_exit": p.returncode, "sbom": sbom.name if sbom.exists() else None}
        if p.returncode != 0:
            rec["syft_stderr_tail"] = p.stderr[-1500:]
        if sbom.exists():
            rec["sbom_sha256"] = hashlib.sha256(sbom.read_bytes()).hexdigest()
            gout = out / f"grant-{name}.json"
            g = run([exes["grant"], "-c", "grant-default-config.yaml", "check", sbom.name, "-o", "json", "-f", gout.name, "--no-output"], env, out)
            rec["grant_exit"] = g.returncode
            rec["grant"] = gout.name if gout.exists() else None
            if g.returncode not in (0, 1):
                rec["grant_stderr_tail"] = g.stderr[-1500:]
        results.append(rec)
        print(json.dumps(rec), flush=True)
    meta = {"tools": [{k: t[k] for k in ("name", "version", "url", "sha256")} for t in LOCK["tools"] if t["name"] in exes],
            "grant_policy": "grant-default-config.yaml = output of `grant config` (Grant 0.7.0 defaults, unmodified). Not a project policy.",
            "results": sorted(results, key=lambda r: order.index(r["target"]) if r["target"] in order else len(order))}
    (out / "scan-manifest.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
