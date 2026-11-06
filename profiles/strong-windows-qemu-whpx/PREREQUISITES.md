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
[`qemu-msys2-ucrt64.lock.json`](qemu-msys2-ucrt64.lock.json) (160 packages), each
downloaded, checked against its pinned sha256, and extracted with Windows' built-in
`tar.exe`. Nothing downloaded is executed during A2; no installer, no administrator
rights, no registry, PATH or service change. Removal is deleting `$Prefix`.

In an ordinary (not elevated) PowerShell 7 window:

```powershell
$Repo   = 'D:\src\ai-engineering-harness'
$State  = 'D:\aieh-guest-state'
$LockFile = "$Repo\profiles\strong-windows-qemu-whpx\qemu-msys2-ucrt64.lock.json"
$Dl     = Join-Path $State 'downloads\msys2-ucrt64'
$Prefix = Join-Path $State 'providers\qemu\msys2-ucrt64-11.1.3-1'

# 1. The lock must be the pinned one.
(Get-FileHash $LockFile -Algorithm SHA256).Hash.ToLower()

# 2. Download and check every package.
$Lock = Get-Content $LockFile -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $Dl, $Prefix | Out-Null
$ProgressPreference = 'SilentlyContinue'
$bad = 0
foreach ($p in $Lock.packages) {
  $file = Join-Path $Dl $p.filename
  if (-not (Test-Path $file)) { Invoke-WebRequest -Uri ($Lock.repository.base_url + $p.filename) -OutFile $file }
  if ((Get-FileHash $file -Algorithm SHA256).Hash.ToLower() -ne $p.sha256) { "BAD $($p.filename)"; $bad++ }
}
"packages=$($Lock.packages.Count) bad=$bad"

# 3. Extract, only if every package matched.
if ($bad -eq 0) {
  foreach ($p in $Lock.packages | Where-Object { $_.extract -ne $false }) {
    & "$env:SystemRoot\System32\tar.exe" -xf (Join-Path $Dl $p.filename) -C $Prefix `
      --exclude .PKGINFO --exclude .BUILDINFO --exclude .MTREE --exclude .INSTALL
    if ($LASTEXITCODE -ne 0) { "EXTRACT FAILED $($p.filename)"; $bad++ }
  }
  "extract failures=$bad"
}

# 4. The extracted provider files must match their pins.
foreach ($f in $Lock.extracted_files.PSObject.Properties) {
  '{0} {1}' -f ((Get-FileHash (Join-Path $Prefix $f.Name) -Algorithm SHA256).Hash.ToLower() -eq $f.Value), $f.Name
}
```

Expected:

| Step | Output |
|---|---|
| 1 | `fc93531bc0225015e96c49130fe81ad9349df512990ae2719378401f4f43bb4b` |
| 2 | `packages=160 bad=0` (about 270 MB downloaded) |
| 3 | `extract failures=0` (159 packages extracted; `iso-codes` is checked but not extracted, see the lock) |
| 4 | `True ucrt64/bin/qemu-system-x86_64.exe` (`d8d6aabc07aeaf8b4582269853933763f3e7d2cb651a703643308cf0ba763596`), `True ucrt64/bin/qemu-img.exe` (`0f1ef935298612b06b1c2e71ee73023228221a296b509632d62447dc1b19e009`), `True ucrt64/share/qemu/bios-256k.bin` (`ae6f6aa973aaccc143f57aa960fb035fd9de4daee4ad0cd713322f8c259e7650`) |

Any `BAD`, `EXTRACT FAILED` or `False` line: stop and report; do not retry with other
files.

**Provenance already checked for this lock (F-03.2.1a, 2026-11-06 UTC).** The
`ucrt64.db` repository database (sha256 `65ea9f22…d801`) carries a valid signature by
`5F944B027F7FE2091985AA2EFA11531AA0AA7F57` (Christoph Reiter, MSYS2 development key),
which three MSYS2 master keys certify. The fingerprints were taken from
<https://www.msys2.org/dev/keyring/> and cross-checked with the `msys2-trusted` file in
<https://github.com/msys2/MSYS2-keyring>. All 160 package files matched the database's
sha256 and each carried a valid detached signature by the same key. The lock's sha256
values are copied from that signed database.

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
   placeholder because the generator lands in F-03.2.2; a paused boot runs no guest
   code, so its content is never read.

   ```powershell
   $I = "$State\instances\f0321b-validate"
   if (Test-Path $I) { throw 'instance directory exists' }
   New-Item -ItemType Directory -Path $I | Out-Null
   & "$Prefix\ucrt64\bin\qemu-img.exe" create -f qcow2 -b $Img -F qcow2 "$I\root.qcow2" 40G
   & "$Prefix\ucrt64\bin\qemu-img.exe" create -f qcow2 "$I\scratch.qcow2" 120G
   [IO.File]::WriteAllBytes("$I\seed.iso", (New-Object byte[] 1048576))
   (Get-FileHash "$I\seed.iso" -Algorithm SHA256).Hash.ToLower()
   $P = Get-Content "$Repo\profiles\strong-windows-qemu-whpx\profile.json" -Raw | ConvertFrom-Json
   $map = [ordered]@{
     '{input:image}' = $Img.Replace('\', '/'); '{input:firmware}' = "$Prefix/ucrt64/share/qemu/bios-256k.bin".Replace('\', '/')
     '{input:seed}' = "$I/seed.iso".Replace('\', '/'); '{instance_dir}' = $I.Replace('\', '/')
     '{qemu_prefix}' = $Prefix.Replace('\', '/'); '{instance}' = 'f0321b-validate'
     '{ssh_port}' = '42022'; '{qmp_port}' = '42023' }
   $argv = foreach ($a in $P.launch.argv) { foreach ($k in $map.Keys) { $a = $a.Replace($k, $map[$k]) }; $a }
   $proc = Start-Process -FilePath $Qemu -ArgumentList (@($argv) + '-S') -PassThru -NoNewWindow `
     -RedirectStandardError "$I\stderr.log"
   ```

   Then talk QMP (standard-library Python; the process stays paused meanwhile):

   ```powershell
   python -I -c "import json,socket;s=socket.create_connection(('127.0.0.1',42023),30);f=s.makefile('rw');r=lambda:json.loads(f.readline());print(r());q=lambda c:(f.write(json.dumps({'execute':c})+'\n'),f.flush(),r())[2];print(q('qmp_capabilities'));print(q('query-version'));print(q('query-status'));print(q('query-cpus-fast'));print(q('query-memory-size-summary'));print(q('quit'))"
   $proc.WaitForExit(); $proc.ExitCode
   Get-Content "$I\stderr.log"
   ```

   Expected: the QMP greeting; `query-version` reports 11.1.3; `query-status` reports
   `"running": false` with status `prelaunch`; `query-cpus-fast` lists 8 CPUs;
   `query-memory-size-summary` reports `base-memory` 17179869184; `quit` returns `{}`;
   the exit code is 0; `stderr.log` holds no error. Record the seed placeholder digest
   `30e14955ebf1352266dc2ff8067e68104607e750abb9d3b36582b8af909fcb58`. Afterwards
   delete `$I` (only that directory).

5. **Negative check (falsification).** If `stderr.log` contains
   `WHPX: No accelerator found`, or any other `WHPX:` failure, or QEMU exits before
   QMP answers, the reference profile is **falsified on this host**: record FAIL, and
   `preflight` must report `TIER_UNAVAILABLE` naming A1. Nothing may retry with another
   accelerator (the profile declares no fallback). If QEMU instead rejects an option
   (for example `-cpu max,vmx=off,svm=off` under WHPX), that is a profile defect to
   report to the Overseer, not a reason to edit the command line ad hoc.
