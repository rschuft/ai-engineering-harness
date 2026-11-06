#!/usr/bin/env python3
"""Component lock resolver (F-01.2).

Resolves every artifact in composition/lock/ from upstream, verifies every
hash / integrity / digest against the lock, installs the Python and npm sets
into a throwaway directory, and writes a machine-readable report of the
verified digests and the versions the installers actually installed.

    python -I composition/resolve.py --work <empty directory outside the checkout>

Prerequisites (checked; see composition/lock/README.md): CPython 3.12 with pip
>= 23.1, Node.js >= 24 with npm >= 11, git, and HTTPS access to pypi.org,
files.pythonhosted.org, registry.npmjs.org, github.com, api.github.com,
ghcr.io and registry-1.docker.io / auth.docker.io.

Safety: Python is installed from binary wheels only (--only-binary :all:,
--require-hashes, --no-deps) with `pip install --target`. The single exception
is the lock's `python.reviewed_sdists` allowlist (decision 0002): such an sdist
is built only after its sha256 and its reviewed build-file hashes match, with a
hash-locked setuptools backend installed into its own directory, under
`python -I -S` in a scrubbed environment inside the work directory, and the
result must be one pure-Python (py3, none, any) wheel; any mismatch refuses the
build (exit 1). Installed contents are checked against each RECORD and the
installed digest is computed from RECORD rows, not wheel archive bytes. npm runs with --ignore-scripts and an isolated cache and
config. No installed package is imported or executed; installed versions come
from installer metadata (`pip inspect --path`, npm's hidden lockfile and
`npm ls --json`). OCI images are not pulled: their resolution is a registry
manifest-digest check. Registry tokens are anonymous, kept in memory only and
never printed or written.

Exit codes: 0 every artifact verified and the locked sets fully installed;
1 a verification, installation or version check failed (any mismatch);
2 usage or prerequisite error; 3 every artifact verified but a blocking
`known_gaps` entry in the lock leaves an installed set incomplete.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parent
LOCK_DIR = HERE / "lock"
LOCK_FILE = LOCK_DIR / "components.lock.json"
PYPI_INDEX = "https://pypi.org/simple"
NPM_REGISTRY = "https://registry.npmjs.org/"
UA = "ai-engineering-harness-resolver/1 (+F-01.2)"
INDEX_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


class Fail(Exception):
    pass


# ---------------------------------------------------------------- utilities
class Checks:
    def __init__(self):
        self.items = []

    def add(self, cid, ok, detail=""):
        self.items.append({"id": cid, "status": "pass" if ok else "fail", "detail": detail})
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {cid}{(': ' + detail) if detail and not ok else ''}", flush=True)
        return ok

    def failed(self):
        return [c for c in self.items if c["status"] != "pass"]


def norm_name(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def lf_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path, algo: str) -> bytes:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.digest()


def http(url, headers=None, method="GET", tries=4):
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers=hdrs, method=method)
        try:
            return urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(2 ** attempt)  # bounded retry back-off for transient network errors
    raise Fail(f"GET {url} failed after {tries} attempts: {last}")


def download(url, dest: Path, algos=("sha256",)):
    dest.parent.mkdir(parents=True, exist_ok=True)
    hs = {a: hashlib.new(a) for a in algos}
    with http(url) as r, open(dest, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            f.write(chunk)
            for h in hs.values():
                h.update(chunk)
    return {a: h.digest() for a, h in hs.items()}


def run(cmd, cwd=None, env=None, capture=True):
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    return p


def tool_version(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (p.stdout or p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def vtuple(s):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def clean_env(extra=None):
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("NPM_CONFIG_", "PIP_", "PYTHON", "UV_", "NODE_OPTIONS"))}
    env.update(extra or {})
    return env


# ---------------------------------------------------------------- prerequisites
def prerequisites(checks):
    info = {"platform": f"{sys.platform}/{platform.machine()}", "python": platform.python_version(),
            "python_implementation": platform.python_implementation()}
    ok = True
    ok &= checks.add("prereq.python", sys.version_info[:2] == (3, 12) and platform.python_implementation() == "CPython",
                     f"CPython 3.12 required, found {info['python_implementation']} {info['python']}")
    pipv = tool_version([sys.executable, "-I", "-m", "pip", "--version"]) or ""
    info["pip"] = pipv.split(" from ")[0]
    ok &= checks.add("prereq.pip", bool(pipv) and vtuple(pipv.split()[1]) >= (23, 1), f"pip >= 23.1 required, found {pipv!r}")
    node = shutil.which("node")
    npm = shutil.which("npm")
    git = shutil.which("git")
    nodev = tool_version([node, "--version"]) if node else None
    npmv = tool_version([npm, "--version"]) if npm else None
    gitv = tool_version([git, "--version"]) if git else None
    info.update({"node": nodev, "npm": npmv, "git": gitv})
    ok &= checks.add("prereq.node", bool(nodev) and vtuple(nodev) >= (24,), f"Node >= 24 required, found {nodev!r}")
    ok &= checks.add("prereq.npm", bool(npmv) and vtuple(npmv) >= (11,), f"npm >= 11 required, found {npmv!r}")
    ok &= checks.add("prereq.git", bool(gitv), "git required")
    return ok, info, npm, git


# ---------------------------------------------------------------- sources
def resolve_sources(lock, checks, git):
    out = []
    env = clean_env({"GIT_TERMINAL_PROMPT": "0"})
    for s in lock["sources"]:
        tag = s["tag"]
        url = s["repository"].rstrip("/") + ".git"
        p = run([git, "-c", "credential.helper=", "ls-remote", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], env=env)
        refs = {}
        for line in (p.stdout or "").splitlines():
            sha, _, ref = line.partition("\t")
            refs[ref] = sha
        direct = refs.get(f"refs/tags/{tag}")
        peeled = refs.get(f"refs/tags/{tag}^{{}}")
        if s.get("tag_type") == "annotated":
            ok = p.returncode == 0 and direct == s.get("tag_object") and peeled == s["commit"]
        else:
            ok = p.returncode == 0 and direct == s["commit"] and peeled is None
        checks.add(f"source.{s['id']}", ok, f"{tag}: observed tag={direct} peeled={peeled}, locked commit {s['commit']}")
        out.append({"id": s["id"], "repository": s["repository"], "tag": tag, "commit": peeled or direct, "verified": ok})
    return out


# ---------------------------------------------------------------- python
def parse_requirements(path: Path):
    pins = {}
    cur = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9._-]+)==([^\s\\;]+)", line)
        if m:
            cur = norm_name(m.group(1))
            if cur in pins:
                raise Fail(f"{path.name}: duplicate pin {cur}")
            pins[cur] = {"version": m.group(2), "hashes": set()}
        for h in re.findall(r"--hash=sha256:([0-9a-f]{64})", line):
            if cur is None:
                raise Fail(f"{path.name}: hash before any requirement")
            pins[cur]["hashes"].add(h)
    for n, p in pins.items():
        if not p["hashes"]:
            raise Fail(f"{path.name}: {n} has no hash")
    return pins


def dist_name_version(filename: str):
    if filename.endswith(".whl"):
        parts = filename[:-4].split("-")
        return norm_name(parts[0]), parts[1]
    m = re.match(r"^(.+)-([^-]+)\.(tar\.gz|zip)$", filename)
    if not m:
        raise Fail(f"unrecognised distribution file {filename}")
    return norm_name(m.group(1)), m.group(2)


def host_target():
    mach = platform.machine().lower()
    if sys.platform == "win32" and mach in ("amd64", "x86_64"):
        return "windows-x86_64"
    if sys.platform.startswith("linux") and mach in ("x86_64", "amd64"):
        return "linux-x86_64"
    if sys.platform.startswith("linux") and mach in ("aarch64", "arm64"):
        return "linux-aarch64"
    return None


def pypi_file_url(name, version, filename):
    with http(f"https://pypi.org/pypi/{name}/{version}/json") as r:
        meta = json.load(r)
    for u in meta.get("urls", []):
        if u["filename"] == filename:
            return u["url"], u["digests"]["sha256"]
    raise Fail(f"{filename} not published for {name} {version}")


def resolve_python(lock, checks, work: Path, observations):
    py = lock["python"]
    res = {"interpreter": py["interpreter"], "targets": {}, "coupled_pins": [], "reviewed_sdists": []}
    installed = {}
    pins = {}
    for target, spec in py["platforms"].items():
        path = LOCK_DIR / spec["file"]
        pins[target] = parse_requirements(path)
        checks.add(f"python.lock.{target}.count", len(pins[target]) == spec["pins"],
                   f"{len(pins[target])} pins in file, lock records {spec['pins']}")
    # internal consistency of the lock
    for target, p in pins.items():
        for d in py["direct"]:
            e = p.get(norm_name(d["name"]))
            checks.add(f"python.lock.{target}.direct.{d['name']}",
                       bool(e) and e["version"] == d["version"] and d["sha256"] in e["hashes"],
                       f"expected {d['name']}=={d['version']} with sha256 {d['sha256']}")
        for b in py.get("reviewed_sdists", []):
            checks.add(f"python.lock.{target}.reviewed-sdist-absent.{b['name']}", norm_name(b["name"]) not in p,
                       "a reviewed sdist must not appear in a wheels-only requirements file")
    names = set().union(*[set(p) for p in pins.values()])
    for n in sorted(names):
        vs = {t: p[n]["version"] for t, p in pins.items() if n in p}
        if len(set(vs.values())) != 1:
            checks.add(f"python.lock.cross-platform-version.{n}", False, f"versions differ across targets: {vs}")
    host = host_target()
    if not checks.add("python.host-target", host in py["platforms"], f"host {sys.platform}/{platform.machine()} is not a locked target"):
        host = None
    cache = work / "cache" / "pip"
    base = [sys.executable, "-I", "-X", "utf8", "-m", "pip"]
    common = ["--isolated", "--disable-pip-version-check", "--no-input", "--cache-dir", cache]
    env = clean_env()
    for target, spec in py["platforms"].items():
        ddir = work / "python" / "download" / target
        ddir.mkdir(parents=True, exist_ok=True)
        cmd = base + ["download"] + common + ["--index-url", PYPI_INDEX, "--only-binary", ":all:", "--no-deps", "--require-hashes",
                                               "-r", LOCK_DIR / spec["file"], "-d", ddir]
        if target != host:
            for plat in spec["pip_download"]["platform"]:
                cmd += ["--platform", plat]
            cmd += ["--python-version", py["interpreter"]["version"], "--implementation", "cp"]
        p = run(cmd, env=env)
        ok = checks.add(f"python.download.{target}", p.returncode == 0, (p.stderr or "")[-2000:])
        files = []
        seen = {}
        for f in sorted(ddir.iterdir()):
            n, v = dist_name_version(f.name)
            digest = file_hash(f, "sha256").hex()
            pin = pins[target].get(n)
            good = bool(pin) and pin["version"] == v and digest in pin["hashes"] and f.name.endswith(".whl")
            if not good:
                checks.add(f"python.verify.{target}.{f.name}", False, f"sha256 {digest} / version {v} not in lock (or not a wheel)")
            seen[n] = seen.get(n, 0) + 1
            files.append({"name": n, "version": v, "file": f.name, "sha256": digest, "verified": good})
        missing = sorted(set(pins[target]) - set(seen))
        dup = sorted(n for n, c in seen.items() if c > 1)
        checks.add(f"python.verify.{target}", ok and not missing and not dup and all(x["verified"] for x in files),
                   f"missing={missing} duplicate={dup}")
        res["targets"][target] = {"file": spec["file"], "pins": len(pins[target]), "downloaded": files,
                                  "verification": "download + sha256 against lock" + (" + host install" if target == host else " (not installed: non-host target)")}
    # reviewed sdists (decision 0002): verify, then build to a pure-Python wheel
    built_dir = work / "python" / "built"
    built = build_reviewed_sdists(py, checks, work, base, common, env, built_dir, res, observations)
    # host install
    if host:
        site = work / "python" / "site"
        reqs = work / "python" / "install-requirements.txt"
        lines = (LOCK_DIR / py["platforms"][host]["file"]).read_text(encoding="utf-8").replace("\r\n", "\n")
        for b in built:
            lines += f"{b['name']}=={b['version']} \\\n    --hash=sha256:{b['wheel_sha256']}\n"
        reqs.write_text(lines, encoding="utf-8")
        cmd = base + ["install"] + common + ["--no-index", "--find-links", work / "python" / "download" / host,
                                              "--find-links", built_dir,
                                              "--only-binary", ":all:", "--no-deps", "--require-hashes", "--no-compile",
                                              "--target", site, "-r", reqs]
        p = run(cmd, env=env)
        checks.add("python.install.host", p.returncode == 0, (p.stderr or "")[-2000:])
        p = run(base + ["inspect", "--isolated", "--disable-pip-version-check", "--path", site], env=env)
        got = {}
        packages = {}
        if checks.add("python.inspect.host", p.returncode == 0, (p.stderr or "")[-1000:]):
            for d in json.loads(p.stdout)["installed"]:
                n = norm_name(d["metadata"]["name"])
                got[n] = d["metadata"]["version"]
                rec_ok, rec_digest, nfiles = record_digest(Path(d["metadata_location"]), site)
                checks.add(f"python.installed.record.{n}", rec_ok, "an installed file does not match its RECORD hash")
                packages[n] = {"version": d["metadata"]["version"], "record_sha256": rec_digest, "files": nfiles}
        want = {n: e["version"] for n, e in pins[host].items()}
        want.update({norm_name(b["name"]): b["version"] for b in py.get("reviewed_sdists", [])})
        diff = {n: (want.get(n), got.get(n)) for n in set(want) | set(got) if want.get(n) != got.get(n)}
        checks.add("python.installed-equals-lock", not diff and bool(got), f"lock vs installed differences: {diff}")
        installed = {"target": host, "path": "python/site", "source": "pip inspect --path + RECORD", "count": len(got),
                     "versions": dict(sorted(got.items())),
                     "contents": {"method": "per package: sha256 over the sorted (path, hash, size) rows of its RECORD, after "
                                            "re-hashing every listed file on disk and checking it against RECORD",
                                  "packages": dict(sorted(packages.items()))}}
    # coupled pins: download and verify, never install
    for e in py.get("coupled_pins", []):
        url, published = pypi_file_url(e["name"], e["version"], e["file"])
        dest = work / "python" / "coupled_pins" / e["file"]
        digest = download(url, dest)["sha256"].hex()
        ok = digest == e["sha256"] == published
        checks.add(f"python.coupled_pins.{e['name']}", ok, f"locked {e['sha256']} downloaded {digest} pypi {published}")
        res["coupled_pins"].append({"name": e["name"], "version": e["version"], "file": e["file"], "sha256": digest,
                                    "verified": ok, "installed": False})
    return res, installed


# ---------------------------------------------------------------- reviewed sdists (decision 0002)
BUILD_CODE = """
import os, sys
backend, src, out = sys.argv[1:4]
sys.path[:0] = [backend]
os.chdir(src)
from setuptools import build_meta
print("WHEEL=" + build_meta.__legacy__.build_wheel(out))
"""
COMPILED_SUFFIXES = (".so", ".pyd", ".dll", ".dylib", ".exe", ".a", ".lib", ".o")


def build_env(work: Path, epoch: int):
    """A scrubbed environment built from nothing: no inherited variables, hence no credentials or tokens."""
    home = work / "python" / "build-home"
    tmp = work / "python" / "build-tmp"
    for d in (home, tmp):
        d.mkdir(parents=True, exist_ok=True)
    env = {"SOURCE_DATE_EPOCH": str(epoch), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home), "LOCALAPPDATA": str(home),
           "TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp), "LC_ALL": "C.UTF-8"}
    if sys.platform == "win32":
        sysroot = os.environ.get("SYSTEMROOT", "C:\\Windows")
        env.update({"SYSTEMROOT": sysroot, "PATH": os.path.join(sysroot, "System32")})
    else:
        env["PATH"] = "/usr/bin:/bin"
    return env


def inspect_sdist(archive: Path, spec):
    """Check the archive as data against the review: member count, no links, safe paths, build-file hashes."""
    import tarfile
    problems, observed = [], {}
    top = spec["archive"]["top_dir"]
    with tarfile.open(archive) as t:
        members = t.getmembers()
        for m in members:
            if m.issym() or m.islnk() or not (m.isfile() or m.isdir()):
                problems.append(f"non-regular member {m.name}")
            if m.name.startswith(("/", "\\")) or ".." in Path(m.name).parts or not (m.name == top or m.name.startswith(top + "/")):
                problems.append(f"unsafe path {m.name}")
        if len(members) != spec["archive"]["members"]:
            problems.append(f"{len(members)} members, review recorded {spec['archive']['members']}")
        for name, want in spec["reviewed_build_files"].items():
            try:
                got = hashlib.sha256(t.extractfile(name).read()).hexdigest()
            except (KeyError, AttributeError):
                got = None
            observed[name] = got
            if got != want:
                problems.append(f"{name}: sha256 {got} != reviewed {want}")
        names = {m.name for m in members}
        for extra in ("pyproject.toml", "setup.py", "setup.cfg"):
            n = f"{top}/{extra}"
            if n in names and n not in spec["reviewed_build_files"]:
                problems.append(f"unreviewed build file {n}")
    return problems, observed


def check_pure_wheel(path: Path, name: str, version: str):
    import zipfile
    problems = []
    parts = path.name[:-4].split("-")
    if len(parts) != 5 or norm_name(parts[0]) != norm_name(name) or parts[1] != version:
        problems.append(f"unexpected wheel name {path.name}")
    else:
        py_tags, abi, plat = parts[2].split("."), parts[3], parts[4]
        if not (set(py_tags) <= {"py3", "py2"} and "py3" in py_tags and abi == "none" and plat == "any"):
            problems.append(f"wheel tag {parts[2]}-{abi}-{plat} is not pure Python")
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.lower().endswith(COMPILED_SUFFIXES):
                problems.append(f"compiled member {n}")
        wheel_meta = [n for n in z.namelist() if n.endswith(".dist-info/WHEEL")]
        text = z.read(wheel_meta[0]).decode() if len(wheel_meta) == 1 else ""
        if "Root-Is-Purelib: true" not in text:
            problems.append("WHEEL does not declare Root-Is-Purelib: true")
        for line in text.splitlines():
            if line.startswith("Tag:") and not line.strip().endswith("-none-any"):
                problems.append(f"WHEEL {line.strip()}")
    return problems


def build_reviewed_sdists(py, checks, work, base, common, env, built_dir, res, observations):
    import tarfile
    specs = py.get("reviewed_sdists", [])
    if not specs:
        return []
    built = []
    # hash-locked build backend, wheels only, into its own directory (never the install target)
    breq = LOCK_DIR / py["build_requirements"]["file"]
    bwheels = work / "python" / "build-backend-wheels"
    backend = work / "python" / "build-backend"
    p = run(base + ["download"] + common + ["--index-url", PYPI_INDEX, "--only-binary", ":all:", "--no-deps", "--require-hashes",
                                            "-r", breq, "-d", bwheels], env=env)
    ok = checks.add("python.build-backend.download", p.returncode == 0, (p.stderr or "")[-1500:])
    p = run(base + ["install"] + common + ["--no-index", "--find-links", bwheels, "--only-binary", ":all:", "--no-deps",
                                           "--require-hashes", "--no-compile", "--target", backend, "-r", breq], env=env)
    backend_ok = checks.add("python.build-backend.install", ok and p.returncode == 0, (p.stderr or "")[-1500:])
    res["build_backend"] = {"file": py["build_requirements"]["file"],
                            "wheels": [{"file": f.name, "sha256": file_hash(f, "sha256").hex()}
                                       for f in sorted(bwheels.iterdir())] if bwheels.exists() else []}
    for spec in specs:
        cid = f"python.reviewed-sdist.{spec['name']}"
        entry = {"name": spec["name"], "version": spec["version"], "file": spec["file"], "decision": spec["decision"],
                 "reviewer": spec["reviewer"], "review_date": spec["review_date"]}
        res["reviewed_sdists"].append(entry)
        url, published = pypi_file_url(spec["name"], spec["version"], spec["file"])
        archive = work / "python" / "reviewed-sdists" / spec["file"]
        digest = download(url, archive)["sha256"].hex()
        hash_ok = checks.add(f"{cid}.sdist-sha256", digest == spec["sha256"] == published,
                             f"REFUSED to build: sdist sha256 {digest} (PyPI {published}) != reviewed {spec['sha256']}")
        entry["sdist_sha256"] = digest if hash_ok else None
        if not hash_ok:
            continue
        problems, observed = inspect_sdist(archive, spec)
        review_ok = checks.add(f"{cid}.review", not problems, "REFUSED to build: " + "; ".join(problems))
        entry["reviewed_build_files"] = observed if review_ok else None
        if not (review_ok and backend_ok):
            continue
        src_root = work / "python" / "sdist-src" / spec["name"]
        with tarfile.open(archive) as t:
            t.extractall(src_root, filter="data")
        src = src_root / spec["archive"]["top_dir"]
        out = work / "python" / "sdist-out" / spec["name"]
        out.mkdir(parents=True, exist_ok=True)
        benv = build_env(work, spec["build"]["source_date_epoch"])
        p = run([sys.executable, "-I", "-S", "-X", "utf8", "-c", BUILD_CODE, backend, src, out], cwd=src, env=benv)
        wheels = sorted(out.glob("*.whl"))
        build_ok = checks.add(f"{cid}.build", p.returncode == 0 and len(wheels) == 1,
                              f"exit {p.returncode}, wheels {[w.name for w in wheels]}: {(p.stderr or '')[-1500:]}")
        if not build_ok:
            continue
        whl = wheels[0]
        pure = check_pure_wheel(whl, spec["name"], spec["version"])
        if not checks.add(f"{cid}.pure-python", not pure, "REFUSED: " + "; ".join(pure)):
            continue
        built_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(whl, built_dir / whl.name)
        wsha = file_hash(whl, "sha256").hex()
        entry.update({"wheel": whl.name, "pure_python": True, "build_env_keys": sorted(benv),
                      "source_date_epoch": spec["build"]["source_date_epoch"]})
        observations.setdefault("reviewed_sdist_wheel_sha256", {})[whl.name] = wsha
        built.append({"name": spec["name"], "version": spec["version"], "wheel_sha256": wsha})
    return built


def record_digest(dist_info: Path, site: Path):
    """Re-hash every file listed in RECORD and digest the (path, hash, size) rows. Independent of wheel archive bytes."""
    import csv
    rows, ok = [], True
    with open(dist_info / "RECORD", newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 3 or not row[1]:
                continue
            path, h, size = row[0].replace("\\", "/"), row[1], row[2]
            # pip --target records scripts relative to its temporary site-packages (e.g. ../../bin/x);
            # it then moves them to <target>/bin, so strip the leading ../ components.
            while path.startswith("../"):
                path = path[3:]
            algo, _, b64 = h.partition("=")
            try:
                actual = base64.urlsafe_b64encode(file_hash(site / path, algo)).rstrip(b"=").decode()
            except (OSError, ValueError):
                actual = None
            if actual != b64:
                ok = False
            rows.append((path, h, size))
    rows.sort()
    return ok, hashlib.sha256("\n".join(",".join(r) for r in rows).encode()).hexdigest(), len(rows)


# ---------------------------------------------------------------- npm
def check_integrity(path: Path, integrity: str):
    for item in integrity.split():
        algo, _, b64 = item.partition("-")
        if algo in ("sha512", "sha384", "sha256", "sha1"):
            if file_hash(path, algo) == base64.b64decode(b64):
                return True
    return False


def resolve_npm(lock, checks, work: Path, npm):
    spec = lock["npm"]
    proj = work / "npm" / "project"
    proj.mkdir(parents=True, exist_ok=True)
    for f in ("package.json", "package-lock.json"):
        shutil.copyfile(LOCK_DIR / spec["dir"] / f, proj / f)
    plock = json.loads((proj / "package-lock.json").read_text(encoding="utf-8"))
    pkgs = {k: v for k, v in plock["packages"].items() if k}
    pj = json.loads((proj / "package.json").read_text(encoding="utf-8"))
    checks.add("npm.lock.version", plock.get("lockfileVersion") == spec["lockfile_version"], str(plock.get("lockfileVersion")))
    checks.add("npm.lock.entries", len(pkgs) == spec["counts"]["lock_entries"], f"{len(pkgs)} vs {spec['counts']['lock_entries']}")
    for d in spec["direct_and_pinned"]:
        e = pkgs.get(d["lock_path"], {})
        checks.add(f"npm.lock.pinned.{d['name']}", e.get("version") == d["version"] and e.get("integrity") == d["integrity"],
                   f"package-lock has {e.get('version')} {e.get('integrity')}")
    for k, v in pkgs.items():
        if not v.get("inBundle") and not (v.get("integrity") and str(v.get("resolved", "")).startswith(NPM_REGISTRY)):
            checks.add(f"npm.lock.entry.{k}", False, "entry lacks integrity or a registry.npmjs.org resolved URL")
    for name, rng in pj.get("dependencies", {}).items():
        checks.add(f"npm.package-json.exact.{name}", re.fullmatch(r"\d+\.\d+\.\d+", rng) is not None, f"range {rng!r} is not exact")
    userrc = work / "npm" / "user.npmrc"
    globalrc = work / "npm" / "global.npmrc"
    userrc.write_text("")
    globalrc.write_text("")
    flags = ["--registry", NPM_REGISTRY, "--cache", work / "cache" / "npm", "--userconfig", userrc, "--globalconfig", globalrc,
             "--no-update-notifier", "--no-audit", "--no-fund"]
    env = clean_env()
    p = run([npm, "ci", "--ignore-scripts", "--loglevel", "warn"] + flags, cwd=proj, env=env)
    checks.add("npm.ci", p.returncode == 0, (p.stderr or "")[-3000:])
    p = run([npm, "ls", "--all", "--json"] + flags, cwd=proj, env=env)
    ls = {}
    try:
        ls = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        pass
    checks.add("npm.ls", p.returncode == 0 and not ls.get("problems"), str(ls.get("problems", ""))[:2000])
    hidden_path = proj / "node_modules" / ".package-lock.json"
    hidden = json.loads(hidden_path.read_text(encoding="utf-8"))["packages"] if hidden_path.exists() else {}
    installed, skipped, problems = {}, [], []
    for k, v in pkgs.items():
        h = hidden.get(k)
        if h is not None:
            if h.get("version") != v.get("version") or h.get("integrity") != v.get("integrity"):
                problems.append(f"{k}: installed {h.get('version')} {h.get('integrity')} != lock")
            installed[k] = h.get("version")
        elif v.get("optional") or v.get("devOptional"):
            skipped.append(k)
        else:
            problems.append(f"{k}: required entry not installed")
    extra = sorted(k for k in hidden if k and k not in pkgs)
    checks.add("npm.installed-equals-lock", not problems and not extra and bool(installed),
               f"problems={problems[:20]} extra={extra[:20]}")
    # Verify the integrity of every locked tarball npm did not install on this host (other-OS/CPU optionals).
    verified_skipped = []
    for k in skipped:
        v = pkgs[k]
        if v.get("inBundle"):
            verified_skipped.append({"path": k, "version": v.get("version"), "integrity": None,
                                     "verification": "bundled inside its parent tarball (covered by the parent's integrity)"})
            continue
        dest = work / "npm" / "non-host" / (k.replace("/", "__") + ".tgz")
        download(v["resolved"], dest, ())
        ok = check_integrity(dest, v["integrity"])
        checks.add(f"npm.non-host.{k}", ok, f"integrity mismatch for {v['resolved']}")
        verified_skipped.append({"path": k, "version": v.get("version"), "integrity": v["integrity"], "verified": ok,
                                 "verification": "direct download of resolved tarball + integrity check (not installed on this host)"})
        dest.unlink()
    direct_installed = {n: d.get("version") for n, d in sorted((ls.get("dependencies") or {}).items())}
    for d in spec["direct_and_pinned"]:
        if d["lock_path"] in installed:
            checks.add(f"npm.installed.{d['name']}", installed[d["lock_path"]] == d["version"], f"installed {installed[d['lock_path']]}")
    res = {"lockfile": spec["lockfile"], "lock_entries": len(pkgs),
           "installed_by_npm_ci": len(installed), "not_installed_on_host_verified_by_download": verified_skipped,
           "integrity": {k: v.get("integrity") for k, v in sorted(pkgs.items())}}
    inst = {"path": "npm/project/node_modules", "source": "node_modules/.package-lock.json (npm ci) + npm ls --all --json",
            "count": len(installed), "direct": direct_installed, "versions": dict(sorted(installed.items()))}
    return res, inst


# ---------------------------------------------------------------- oci
def registry_for(repository):
    host, _, name = repository.partition("/")
    if host == "docker.io":
        return "https://registry-1.docker.io", name
    return f"https://{host}", name


def oci_get(base, name, ref, tokens, method="GET"):
    url = f"{base}/v2/{name}/manifests/{ref}"
    hdr = {"Accept": INDEX_TYPES}
    key = (base, name)
    if key in tokens:
        hdr["Authorization"] = "Bearer " + tokens[key]
    try:
        return http(url, hdr, method)
    except urllib.error.HTTPError as e:
        if e.code != 401 or key in tokens:
            raise
        chal = e.headers.get("WWW-Authenticate", "")
        params = dict(re.findall(r'(\w+)="([^"]*)"', chal))
        q = {"scope": params.get("scope", f"repository:{name}:pull")}
        if "service" in params:
            q["service"] = params["service"]
        with http(params["realm"] + "?" + urllib.parse.urlencode(q)) as r:
            tok = json.load(r)
        tokens[key] = tok.get("token") or tok.get("access_token")  # anonymous; memory only
        hdr["Authorization"] = "Bearer " + tokens[key]
        return http(url, hdr, method)


def resolve_oci(lock, checks):
    tokens, out, observed = {}, [], {}
    for o in lock["oci"]:
        base, name = registry_for(o["repository"])
        cid = f"oci.{o['id']}"
        try:
            with oci_get(base, name, o["index_digest"], tokens) as r:
                body = r.read()
                hdr_digest = r.headers.get("Docker-Content-Digest")
            calc = "sha256:" + hashlib.sha256(body).hexdigest()
            idx = json.loads(body)
            ok = checks.add(f"{cid}.index", calc == o["index_digest"] and hdr_digest in (None, o["index_digest"])
                            and idx.get("mediaType") == o["media_type"],
                            f"computed {calc} header {hdr_digest} mediaType {idx.get('mediaType')}")
            plats = {}
            for m in idx.get("manifests", []):
                pl = m.get("platform", {})
                if pl.get("os") == "linux":
                    plats[f"linux/{pl.get('architecture')}" + (f"/{pl['variant']}" if pl.get("variant") else "")] = m["digest"]
            verified_plats = {}
            for plat, dg in o["platform_digests"].items():
                good = plats.get(plat) == dg
                if good:
                    with oci_get(base, name, dg, tokens) as r:
                        good = "sha256:" + hashlib.sha256(r.read()).hexdigest() == dg
                checks.add(f"{cid}.{plat}", good, f"index lists {plats.get(plat)}, locked {dg}")
                verified_plats[plat] = dg if good else None
            with oci_get(base, name, o["tag_at_lock_time"], tokens, method="HEAD") as r:
                observed[o["id"]] = r.headers.get("Docker-Content-Digest")
            out.append({"id": o["id"], "ref": f"{o['repository']}@{o['index_digest']}", "index_digest": calc if ok else None,
                        "platform_digests": verified_plats, "verification": "registry manifest-digest check (image not pulled)"})
        except (urllib.error.HTTPError, Fail, OSError, ValueError) as e:
            checks.add(f"{cid}.index", False, f"{type(e).__name__}: {e}")
            out.append({"id": o["id"], "index_digest": None})
    return out, observed


# ---------------------------------------------------------------- release assets
def resolve_release_assets(lock, checks, work: Path):
    out, sums, api = [], {}, {}
    for a in lock["release_assets"]:
        cid = f"release.{a['component']}.{a['name']}"
        try:
            if a["method"] == "download":
                dest = work / "release" / a["component"] / a["name"]
                digest = download(a["url"], dest)["sha256"].hex()
                sums[a["url"]] = dest.read_text(encoding="utf-8")
                ok = digest == a["sha256"]
                detail = f"downloaded sha256 {digest}"
            elif a["method"] == "checksum-file-line":
                text = sums.get(a["checksum_file"])
                if text is None:
                    raise Fail("checksum file must be a locked 'download' asset listed earlier")
                lines = {ln.split()[-1].lstrip("*"): ln.split()[0] for ln in text.splitlines() if ln.strip()}
                digest = lines.get(a["name"])
                ok = digest == a["sha256"]
                detail = f"verified checksum file lists {digest}"
            elif a["method"] == "per-asset-checksum-file":
                with http(a["checksum_file"]) as r:
                    digest = r.read().decode().split()[0]
                ok = digest == a["sha256"]
                detail = f"published .sha256 lists {digest}"
            elif a["method"] == "github-asset-digest":
                if a["release_api"] not in api:
                    with http(a["release_api"], {"Accept": "application/vnd.github+json"}) as r:
                        api[a["release_api"]] = {x["name"]: x.get("digest") for x in json.load(r)["assets"]}
                digest = (api[a["release_api"]].get(a["name"]) or "").removeprefix("sha256:")
                ok = digest == a["sha256"]
                detail = f"GitHub asset digest {digest}"
            else:
                raise Fail(f"unknown method {a['method']}")
        except (urllib.error.HTTPError, Fail, OSError, ValueError) as e:
            ok, digest, detail = False, None, f"{type(e).__name__}: {e}"
        checks.add(cid, ok, detail)
        out.append({"component": a["component"], "name": a["name"], "sha256": digest if ok else None, "method": a["method"],
                    "content_downloaded": a["method"] == "download"})
    return out


# ---------------------------------------------------------------- main
def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", required=True, help="empty or absent directory OUTSIDE the checkout for downloads, caches and installs")
    ap.add_argument("--report", help="report path (default: <work>/report.json)")
    args = ap.parse_args(argv)
    work = Path(args.work).resolve()
    if work == CHECKOUT or CHECKOUT in work.parents:
        print(f"--work must be outside the checkout {CHECKOUT}", file=sys.stderr)
        return 2
    if work.exists() and any(work.iterdir()):
        print(f"--work {work} must be empty or absent (clean caches)", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report).resolve() if args.report else work / "report.json"
    started = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    checks = Checks()
    ok, host, npm, git = prerequisites(checks)
    if not ok:
        print("prerequisites not met", file=sys.stderr)
        return 2
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    lock_files = {str(p.relative_to(LOCK_DIR)).replace("\\", "/"): lf_sha256(p)
                  for p in sorted(LOCK_DIR.rglob("*")) if p.is_file() and p.suffix in (".json", ".txt", ".in")}
    resolution = {"lock_files_sha256_lf": lock_files}
    installed = {}
    observations = {}
    print("== sources", flush=True)
    resolution["sources"] = resolve_sources(lock, checks, git)
    print("== python", flush=True)
    try:
        resolution["python"], installed["python"] = resolve_python(lock, checks, work, observations)
    except (Fail, OSError, ValueError, urllib.error.HTTPError) as e:
        checks.add("python", False, f"{type(e).__name__}: {e}")
    print("== npm", flush=True)
    try:
        resolution["npm"], installed["npm"] = resolve_npm(lock, checks, work, npm)
    except (Fail, OSError, ValueError, urllib.error.HTTPError) as e:
        checks.add("npm", False, f"{type(e).__name__}: {e}")
    print("== oci", flush=True)
    resolution["oci"], observed_tags = resolve_oci(lock, checks)
    ci = lock["conversation_image"]
    match = next((o for o in resolution["oci"] if o.get("ref") == ci["ref"]), None)
    ci_ok = checks.add("conversation_image", bool(match) and match.get("index_digest") == ci["index_digest"]
                       and match.get("platform_digests") == ci["platform_digests"], f"{ci['ref']} not verified")
    resolution["conversation_image"] = {"ref": ci["ref"], "index_digest": ci["index_digest"] if ci_ok else None,
                                        "platform_digests": ci["platform_digests"] if ci_ok else None,
                                        "verification": ci["resolution_method"], "conformance": ci["conformance"]}
    print("== release assets", flush=True)
    resolution["release_assets"] = resolve_release_assets(lock, checks, work)
    gaps = [g for g in lock.get("known_gaps", []) if g.get("severity") == "blocking"]
    resolution["known_gaps"] = [{"id": g["id"], "blocks": g["blocks"]} for g in gaps]
    failed = checks.failed()
    status, code = ("failed", 1) if failed else (("incomplete", 3) if gaps else ("complete", 0))
    resolution_digest = hashlib.sha256(canonical(resolution).encode()).hexdigest()
    installed_digest = hashlib.sha256(canonical(installed).encode()).hexdigest()
    report = {
        "schema": "ai-engineering-harness/component-resolution-report", "schema_version": 1,
        "status": status, "exit_code": code,
        "resolution_digest": resolution_digest, "installed_digest": installed_digest,
        "conversation_image": resolution["conversation_image"],
        "summary": {"checks": len(checks.items), "failed": len(failed), "known_blocking_gaps": [g["id"] for g in gaps],
                    "python_installed": installed.get("python", {}).get("count"), "npm_installed": installed.get("npm", {}).get("count")},
        "resolution": resolution,
        "installed": installed,
        "failed_checks": failed,
        "checks": checks.items,
        "observations": dict(observations, oci_tag_currently_resolves_to=observed_tags,
                             note="informational, outside the digests: the lock never consumes tags, and a rebuilt "
                                  "reviewed-sdist wheel's archive bytes may legitimately differ (decision 0002)"),
        "run": {"started": started, "finished": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                "host": host, "work": str(work), "checkout": str(CHECKOUT)},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"status={status} exit={code} checks={len(checks.items)} failed={len(failed)}")
    print(f"resolution_digest={resolution_digest}")
    print(f"installed_digest={installed_digest}")
    print(f"conversation_image={resolution['conversation_image']['ref']} verified={ci_ok}")
    print(f"report={report_path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
