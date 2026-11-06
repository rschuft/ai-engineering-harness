# 0002 - Reviewed-sdist exception for component resolution

Status: Accepted (Overseer) - 2026-11-06
Gate: none earned. This is supply-chain mechanics for the development resolver. It
changes no product isolation boundary, provider choice, or authority, so the Overseer
decided it and recorded the reasoning here.

## Context
F-01.2 resolves the locked composition with binary wheels only, because building an
sdist executes package code on the host. `openhands-tools` 1.60.1 requires
`func-timeout>=4.3.5`, and PyPI has never published a wheel for any `func-timeout`
release (3.0.0 to 4.3.5). Without an install path for it, the Python set is incomplete
and the F-01 parent proof ("reports the actual installed versions") cannot pass.

The Overseer downloaded `func_timeout-4.3.5.tar.gz` and confirmed its sha256
`74cd3c428ec94f4edfba81f9b2f14904846d5ffccc27c92433b8b5939b5575dd` against PyPI. It
then read the archive as data, without executing anything. The archive holds 41
members: pure-Python sources, tests, and docs, with no compiled extension. `setup.py`
reads `README.rst` and calls `setuptools.setup()`. It makes no network access, starts
no subprocess, and uses no custom build commands. `setup.cfg` holds only egg_info
tags. The package declares no dependencies. Its license is LGPLv2/2.1.

## Decision
The resolver may build and install an sdist only when all of these hold:
1. The package is listed in the lock's reviewed-sdist allowlist, with its exact sdist
   sha256, the reviewed build files, the reviewer, and the review date. The only entry
   is `func-timeout` 4.3.5.
2. The sdist is hash-verified before any build step. A hash change invalidates the
   review, and the resolver refuses to build.
3. The build backend and its own dependencies come from hash-locked wheels, so build
   isolation never fetches an unpinned `setuptools`.
4. The build runs inside the resolver's throwaway work directory. Its environment
   contains no credentials. It writes no global or user site directory.
5. The package must be pure Python. Any compiled extension voids the exception.

Every other package stays wheels-only. Adding a package to the allowlist requires the
same review and an amendment to this record.

## Consequences
- The Python set can be installed completely, and F-01.2 can satisfy the F-01 proof.
  Reproducibility is judged on the installed contents and versions. A rebuilt wheel's
  archive bytes may legitimately differ between runs.
- The LGPL license of `func-timeout` is an open distribution item for G-02.1 and
  R-04.1/R-04.2, together with the other items in
  `composition/inventory/LEDGER.md`. One of those is `lmnr-claude-code-proxy` 0.2.0,
  declared `LicenseRef-Proprietary` and pulled in by `openhands-sdk` through `lmnr`.
  The lock only references these packages; it does not redistribute them.
- If a later upstream release publishes a `func-timeout` wheel, prefer the wheel and
  retire the exception.
