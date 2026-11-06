# strong-windows-qemu-whpx: provider prerequisites

Plan leaf F-03.2.1. The profile is [`profile.json`](profile.json); the reasons for
its choices are in [`README.md`](README.md).

Until the Owner has approved and performed A1, A2 and A3, and the Overseer has recorded
each in `evidence/bootstrap-log.md`, this host is unsupported for the strong tier and
`preflight` reports `unavailable` (decision 0003, "Owner act"). Each act is approved
separately (C2). None of them touches WSL, the Owner's distribution or
`%USERPROFILE%\.wslconfig` (C1).

## A1: enable the Windows Hypervisor Platform (elevated, one restart)

1. In a PowerShell window opened with **Run as administrator**, read the state:

   ```powershell
   Get-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform
   ```

2. Apply decision 0003's rule to the output:
   - It prints a `State` line. The feature is available on this edition.
     - `State : Enabled`: stop here; A1 is already satisfied.
     - `State : Disabled`: continue with step 3.
   - It fails with an error that the feature name is unknown. The feature is not
     available on this edition. Stop: the strong tier cannot run locally (contract
     section 12). The remaining route is an explicit remote Incus host
     (`strong-incus-vm` addressed to a named remote).

3. Enable it without an immediate restart:

   ```powershell
   Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -NoRestart
   ```

   Expected: the command completes and reports `RestartNeeded : True`.

4. Restart Windows at a time the Owner chooses. As with any restart, running WSL
   distributions stop; nothing in WSL is reconfigured.

5. After the restart, in an elevated PowerShell again:

   ```powershell
   Get-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform
   ```

   Expected: `State : Enabled`.

## A3: create the guest-state directory (not elevated)

A3 comes before A2 because A2 installs into it. The path is a proposal for the Owner
to approve or replace. It must stay outside the checkout, outside `%USERPROFILE%`,
and contain no comma (contract section 11).

```powershell
$State = 'D:\aieh-guest-state'
New-Item -ItemType Directory -Path $State
icacls $State /inheritance:r /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F"
icacls $State
```

Expected: the directory is created; `icacls` reports `Successfully processed 1 files;
Failed processing 0 files`; the final listing shows only the Owner's account,
`NT AUTHORITY\SYSTEM` and `BUILTIN\Administrators`, each with `(OI)(CI)(F)`. Removing
the inherited entries keeps other local accounts away from guest disks and the
per-instance SSH private keys. If `New-Item` is denied, stop and report: the Owner
then chooses another path, rather than elevating silently.

## A2: install QEMU 11.1.3, user-scoped (not elevated)

Method: the MSYS2 `ucrt64` packages pinned in
[`qemu-msys2-ucrt64.lock.json`](qemu-msys2-ucrt64.lock.json) (159 packages), installed
by [`tools/msys2_lock.py`](../../tools/msys2_lock.py) `install` (standard-library
Python). Windows' built-in `tar.exe` only decodes each archive to an uncompressed
stream on stdout; the tool validates every entry and writes the files itself. Nothing
downloaded is executed during A2: no installer, no `.INSTALL` script, no pacman hook,
no administrator rights, no registry, PATH or service change. Removal is deleting
`$Prefix`.

The tool runs four phases and stops at the first finding:

1. **fetch.** Each package missing from `$Dl` is downloaded from the lock's
   `base_url` over HTTPS with redirects refused, hashed while it streams, and renamed
   into place only when complete. A file already in `$Dl` is re-hashed in place and
   never overwritten. Any sha256 that differs from the lock stops the install.
2. **validate.** Before anything is written, every entry of every archive is listed
   and checked (the lock's `extraction.entry_rules`): no absolute path, drive letter,
   `..`, `.` or empty component, control or Windows-special character, reserved
   device name or trailing dot or space; only regular files and directories;
   installed paths under 250 characters. Links follow `extraction.link_policy`:
   - **Symlinks are refused.** `iso-codes` (470 locale symlinks, data only) is marked
     `"extract": false`: it is downloaded, hashed and validated, not extracted. A
     symlink in any other package stops the install.
   - **Hardlinks are materialised as regular-file copies** (Overseer decision on A2,
     within the Owner's condition 3), and only after checking that the target is a
     regular file earlier in the same package, that link and target are both under
     `ucrt64/`, and that both resolve inside `$Prefix`. Each package's count must
     match the lock's `hardlinks`: `libdeflate` 1, `tcl` 593, `tk` 208, `tzdata` 760.
     No link is ever created on disk.

   The whole resolved set must also pass the overlap check: no path, compared
   case-insensitively, is installed by two packages (shared directories allowed).
3. **extract.** `$Prefix` must not exist; the tool creates it (and only missing
   parents) without `-Force` semantics. Each package except `iso-codes` is read again
   and written entry by entry. Each entry must match its validated listing (name,
   type, link target and order) and each file's bytes must hash to the validated
   value. The members `.PKGINFO`, `.BUILDINFO`, `.MTREE` and `.INSTALL` are skipped.
   Files are created exclusively, so nothing is overwritten.
4. **verify.** Every installed file is compared with the manifest built in step 2
   (sha256 and size, taken from the archives). The tool also checks the lock's
   `extracted_files` pins, that no path is missing or extra, and that the tree holds
   no reparse point and no file with more than one link.

In an ordinary (not elevated) PowerShell 7 window:

```powershell
$Repo     = 'D:\src\ai-engineering-harness'
$State    = 'D:\aieh-guest-state'
$LockFile = "$Repo\profiles\strong-windows-qemu-whpx\qemu-msys2-ucrt64.lock.json"
$Dl       = Join-Path $State 'downloads\msys2-ucrt64'
$Prefix   = Join-Path $State 'providers\qemu\msys2-ucrt64-11.1.3-1'
$Report   = Join-Path $env:TEMP 'aieh-a2-report.json'

# 1. The lock must be the pinned one (profile.json provider.artifact_lock).
(Get-FileHash $LockFile -Algorithm SHA256).Hash.ToLower()

# 2. The install directory must not exist yet. If this prints True, stop.
Test-Path $Prefix

# 3. Install. Add --validate-only to stop after the validate phase.
python -I -B "$Repo\tools\msys2_lock.py" install --lock $LockFile `
  --lock-sha256 69e083362da92d413c56e687ac36300a8a51a913e7cae3c2126bcfb6e45df879 `
  --downloads $Dl --prefix $Prefix --report $Report
```

Expected:

| Step | Output |
|---|---|
| 1 | `69e083362da92d413c56e687ac36300a8a51a913e7cae3c2126bcfb6e45df879` |
| 2 | `False` |
| 3 | `fetch`: `"packages": 159`, `"bad": []`, 267,357,780 bytes |
| 3 | `validate`: `"entries": 53966`, `"rejected": 470` (the `iso-codes` symlinks), the four hardlink counts above, `"overlaps": 0`, `"findings": []`, `"expected_files": 45742`, `"expected_dirs": 2577`, `"expected_bytes": 2598669728` |
| 3 | `extract`: `"packages": 158`, `"failures": 0`, `"materialised_hardlinks"` equal to the four counts above |
| 3 | `verify`: `"installed_files": 45742`, `"installed_bytes": 2598669728`, `"installed_dirs": 2577`; `missing`, `extra`, `missing_dirs`, `extra_dirs`, `mismatch`, `reparse_points`, `non_regular` and `multi_link_files` all 0 |
| 3 | `True ucrt64/bin/qemu-system-x86_64.exe d8d6aabc07aeaf8b4582269853933763f3e7d2cb651a703643308cf0ba763596`, `True ucrt64/bin/qemu-img.exe 0f1ef935298612b06b1c2e71ee73023228221a296b509632d62447dc1b19e009`, `True ucrt64/share/qemu/bios-256k.bin ae6f6aa973aaccc143f57aa960fb035fd9de4daee4ad0cd713322f8c259e7650`, exit code 0 |

A `STOP:` line or a non-zero exit code: stop and report, with the report file. Do not
retry with other files, and do not delete or overwrite anything to work around it.

**How the lock is made.** `tools/msys2_lock.py lock` resolves the closure of
`mingw-w64-ucrt-x86_64-qemu` from the signed `ucrt64.db` with libalpm's dependency
semantics. It honours `depends` with versions, `provides`, `conflicts` and `replaces`:
a package that another repository package replaces and provides is never chosen, and
any conflict left in the set stops it. It checks every archive against the database
sha256, applies the entry rules, link policy and overlap check, and writes the lock.
The lock's `resolution` field records the roots and every provider decision. Run
again with the lock as its own template, the command reproduces it byte for byte:

```powershell
python -I -B "$Repo\tools\msys2_lock.py" lock --db <verified ucrt64.db> `
  --root mingw-w64-ucrt-x86_64-qemu --template $LockFile --downloads $Dl `
  --out <new lock> --report <report>
```

**Provenance.** The `ucrt64.db` repository database (sha256 `65ea9f22…d801`) carries
a valid signature by `5F944B027F7FE2091985AA2EFA11531AA0AA7F57` (Christoph Reiter,
MSYS2 development key), which three MSYS2 master keys certify. The fingerprints were
taken from <https://www.msys2.org/dev/keyring/> and cross-checked with the
`msys2-trusted` file in <https://github.com/msys2/MSYS2-keyring> (F-03.2.1a, 2026-11-06
UTC). All 160 package files of the first closure matched the database's sha256 and
each carried a valid detached signature by the same key. The 159 now locked are
among them. The signature was verified again for the re-resolution (2026-11-06 UTC,
`VALIDSIG 5F944B02…7F57`, certified by `…CA25678A`, `…ACD22879` and `…1D3CFDDC`).
The lock's sha256 values are copied from that signed database.

**Correction (2026-11-06).** The first lock (sha256 `fc93531b…bb4b`, 160 packages)
pinned both `sqlite` 3.54.1-2 and `sqlite3` 3.54.1-1. `sqlite` replaces, conflicts
with and provides `sqlite3`, and the two install 130 of the same paths, 66 with
different content. A2 stopped at entry validation before writing anything, and the
lock was re-resolved as above. `sqlite3` is gone, `python` and `libsoup3` take
`sqlite3` from `sqlite`, and nothing else changed.

## F-03.2.1b: provider configuration validation (after A1 to A3 are recorded)

Contract section 10: the provider's own parser accepts the declared configuration,
without starting any untrusted workload. Run in an ordinary PowerShell 7 window, with
`$Repo`, `$State` and `$Prefix` as above.

1. **Schema check.** Every boot input is pinned by digest:

   ```powershell
   python -I -B "$Repo\tools\check_profile.py" --strict "$Repo\profiles\strong-windows-qemu-whpx"
   ```

   Expected: `PASS strong-windows-qemu-whpx`, exit code 0.

2. **Provider binary and accelerator listing.**

   ```powershell
   $Qemu = "$Prefix\ucrt64\bin\qemu-system-x86_64.exe"
   & $Qemu -version
   & $Qemu -accel help
   ```

   Expected: `QEMU emulator version 11.1.3`; the accelerator list includes `whpx`. The
   list shows what the build contains, not that WHPX works; step 4 decides that.

3. **Image.** Download the pinned image into the state directory and check it:

   ```powershell
   $Img = "$State\images\debian-13-genericcloud-amd64-20261103-2651.qcow2"
   New-Item -ItemType Directory -Force -Path "$State\images" | Out-Null
   Invoke-WebRequest -Uri 'https://cloud.debian.org/images/cloud/trixie/20261103-2651/debian-13-genericcloud-amd64-20261103-2651.qcow2' -OutFile $Img
   (Get-FileHash $Img -Algorithm SHA256).Hash.ToLower()
   (Get-FileHash $Img -Algorithm SHA512).Hash.ToLower()
   ```

   Expected: `de9d63f5e5ec5927d7548bc05b6043b87457b8c1cb9bcb95365168e8d0293b4f` and
   `d25999de…f13b535` (the full value is in `profile.json`).

4. **Paused boot with the full declared command line, then QMP `quit`.** The seed is a
   real one from [`tools/nocloud_seed.py`](../../tools/nocloud_seed.py), carrying a
   throwaway ed25519 key generated into the instance directory (never `~/.ssh`). A
   paused boot (`-S`) runs no guest code, so the seed's content is not read yet.
   First re-run in F-03.2.1b with a zero-filled placeholder seed and `-mon`; re-run in
   F-03.2.2a with the generated seed and `-object monitor-qmp`
   ([evidence](../../evidence/F-03.2.2a-seed-and-monitor.md)).

   ```powershell
   $Name = 'f0322a-validate'
   $I = "$State\instances\$Name"
   if (Test-Path $I) { throw 'instance directory exists' }
   foreach ($port in 42022, 42023) {
     if (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) { throw "port $port is in use" } }
   $P = Get-Content "$Repo\profiles\strong-windows-qemu-whpx\profile.json" -Raw | ConvertFrom-Json
   $ImgHash = (Get-FileHash $Img -Algorithm SHA256).Hash.ToLower(); $ImgHash
   if ($ImgHash -ne $P.boot_inputs.image.sha256) { throw 'image sha256 mismatch' }
   New-Item -ItemType Directory -Path $I, "$I\ssh" | Out-Null
   & "$env:SystemRoot\System32\OpenSSH\ssh-keygen.exe" -q -t ed25519 -N '' -C $Name -f "$I\ssh\id_ed25519"
   & "$Prefix\ucrt64\bin\qemu-img.exe" create -f qcow2 -b $Img -F qcow2 "$I\root.qcow2" 40G
   & "$Prefix\ucrt64\bin\qemu-img.exe" create -f qcow2 "$I\scratch.qcow2" 120G
   python -I -B "$Repo\tools\nocloud_seed.py" --profile "$Repo\profiles\strong-windows-qemu-whpx" `
     --instance-dir $I --instance-name $Name --public-key "$I\ssh\id_ed25519.pub"
   (Get-FileHash "$I\seed.iso" -Algorithm SHA256).Hash.ToLower()
   $map = [ordered]@{
     '{input:image}' = $Img.Replace('\', '/'); '{input:firmware}' = "$Prefix/ucrt64/share/qemu/bios-256k.bin".Replace('\', '/')
     '{input:seed}' = "$I/seed.iso".Replace('\', '/'); '{instance_dir}' = $I.Replace('\', '/')
     '{qemu_prefix}' = $Prefix.Replace('\', '/'); '{instance}' = $Name
     '{ssh_port}' = '42022'; '{qmp_port}' = '42023' }
   $argv = foreach ($a in $P.launch.argv) { foreach ($k in $map.Keys) { $a = $a.Replace($k, $map[$k]) }; $a }
   $proc = Start-Process -FilePath $Qemu -ArgumentList (@($argv) + '-S') -PassThru -NoNewWindow `
     -RedirectStandardError "$I\stderr.log"
   ```

   Then talk QMP (standard-library Python; the process stays paused meanwhile). Wait
   until QEMU listens on the QMP port or exits, and skip asynchronous events: QEMU sends
   the `SHUTDOWN` event before its reply to `quit`.

   ```powershell
   while (-not $proc.HasExited -and -not (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 42023 -State Listen -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 200 }
   $Qmp = @'
   import json, socket, sys
   f = socket.create_connection(('127.0.0.1', int(sys.argv[1])), 30).makefile('rw')
   def reply():
       while True:
           m = json.loads(f.readline())
           if 'event' not in m:
               return m
   def q(cmd, **args):
       f.write(json.dumps({'execute': cmd, **({'arguments': args} if args else {})}) + '\n')
       f.flush()
       return reply()
   print('greeting', json.dumps(reply()))
   for c in ('qmp_capabilities', 'query-version', 'query-status', 'query-accelerators',
             'query-cpus-fast', 'query-memory-size-summary', 'query-block'):
       print(c, json.dumps(q(c)))
   print('query-named-block-nodes', json.dumps(q('query-named-block-nodes', flat=True)))
   print('qom-list /objects', json.dumps(q('qom-list', path='/objects')))
   print('quit', json.dumps(q('quit')))
   '@
   $Qmp | python -I - 42023
   $proc.WaitForExit(); $proc.ExitCode
   Get-Content "$I\stderr.log"
   ```

   Expected: the QMP greeting; `query-version` reports 11.1.3; `query-status` reports
   `"running": false` with status `prelaunch`; `query-accelerators` reports
   `"enabled": "whpx"`; `query-cpus-fast` lists 8 CPUs; `query-memory-size-summary`
   reports `base-memory` 17179869184; `query-block` lists exactly three devices, whose
   top nodes are `root`, `scratch` (read-write) and `seed` (`"ro": true`), with `root`
   backed by `base`; `query-named-block-nodes` shows `base`, `base-file`, `seed` and
   `seed-file` with `"ro": true`; `qom-list /objects` includes `qmp-monitor` of type
   `child<monitor-qmp>`; `quit` returns `{}`; the exit code is 0; `stderr.log` holds no
   error and no `-mon` deprecation warning. Record the `seed.iso` digest the generator
   prints. Afterwards confirm no `qemu-system-x86_64` process remains, and delete `$I`
   (only that directory, including the throwaway key):

   ```powershell
   Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue
   Remove-Item -Recurse -Force $I; Test-Path $I
   ```

   Expected: no process listed; `False`.

5. **Negative check (falsification).** If `stderr.log` contains
   `WHPX: No accelerator found`, or any other `WHPX:` failure, or QEMU exits before
   QMP answers, the reference profile is **falsified on this host**: record FAIL, and
   `preflight` must report `TIER_UNAVAILABLE` naming A1. Nothing may retry with another
   accelerator (the profile declares no fallback). If QEMU instead rejects an option
   (for example `-cpu max,vmx=off,svm=off` under WHPX), that is a profile defect to
   report to the Overseer, not a reason to edit the command line ad hoc.
