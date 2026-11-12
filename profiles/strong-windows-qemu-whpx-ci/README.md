# strong-windows-qemu-whpx-ci

Plan leaf Q-02.2.1. The CI profile variant of [`strong-windows-qemu-whpx`](../strong-windows-qemu-whpx/README.md):
the dedicated, disposable CI guest of the validation lane
([decision 0016](../../decisions/0016-hostile-ci-threat-model-validation-and-promotion-lanes-and-runner-reach.md)
section 2), with the ceilings and lifetime the Owner confirmed at C-3 (2026-11-11). Files:

| File | Holds |
|---|---|
| [`profile.json`](profile.json) | The declaration: the execution profile's provider, accelerator, image, seed pattern, guards, lifecycle verbs and P1 to P12 contract, with the C-3 ceilings (4 vCPU, 6 GiB, 20 GiB system disk, 40 GiB working disk), its own launch argv and `provisioning.ci_runner` in place of the Agent Server. |
| [`provision.lock.json`](provision.lock.json) | The provisioning artifacts: the Debian Moby closure (the execution profile's snapshot), the job image `docker.io/library/python:3.12-trixie` by index, linux/amd64 manifest, image id and its seven layers, the `gitea-runner` 6.0.0 release binary, the hash-locked Python tools wheel set for linux cp312, and crane. |
| [`../seed/ci/user-data.tmpl`](../seed/ci/user-data.tmpl) | The CI guest's user-data template ([`../seed/README.md`](../seed/README.md#the-ci-guest-seed-q-0221)). |

**What `provisioning.ci_runner` declares.** The runner's binary and system user (in group
`docker`, no login; `agent` stays out), its `config.yaml` (one label naming the job image by its
id; capacity 1; cache, metrics and health check off; no environment, hooks or post-task script;
`docker_host: "-"`; one network per job with IPv6 off; `valid_volumes: []`; `container.volumes`
exactly the read-only exchange and wheel set; the declared container options), its unit (the
loopback only by `IPAddressDeny=any`, started only after registration), its register call (the
token by `--token-file` from `/run`), the `ci-control` sshd directives, the one shared lifetime
of C-3 (a persistent runner, deleted at destroy), the guards of the execution profile verbatim,
and the CI job constraints carried to Q-02.2.2 and Q-02.3.2.
[`tools/check_ci_policy.py`](../../tools/check_ci_policy.py) checks the config, service and
register call against [`policy/ci-runner-profile.json`](../../policy/ci-runner-profile.json);
[`tools/check_profile.py`](../../tools/check_profile.py) checks them against the seed and the
provision lock.

**Status.** Declared and pinned; `tools/check_profile.py --strict` and
`tools/check_ci_policy.py` pass. **Not created, provisioned, registered or run:**
`tools/guest.py` has no CI bindings yet (a later slice of Q-02.2.1), and every live act (the
`ci-control` forward A-1, repository content A-2, an untrusted workload A-3, the proxy listener
A-4, the registration procedure of C-2) is unauthorized (OA-13). Not verified: everything about
a running CI guest, observed at Q-02.2.2. Record:
[`evidence/Q-02.2.1-ci-variant.md`](../../evidence/Q-02.2.1-ci-variant.md).
