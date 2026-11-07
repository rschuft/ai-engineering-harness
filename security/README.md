# Security inventory: principals, protected assets and credential requirements

Plan leaf **S-01.1**, "Inventory principals and protected assets", as of 2026-11-07
(baseline commit `b358a68`). This record is the input that S-01.2 (role-scoped
identities and secret delivery) and S-01.3.x (management API admission and
container-socket isolation) implement and test against.

- **Acceptance of this leaf:** each privileged operation has a named principal, and no
  agent-managed token is described as Owner authority.
- **Inherited parent obligation (S-01, not tested here):** an agent cannot invoke
  privileged conversation creation or reach Owner or admin tokens, even if it controls
  its own workspace.
- **Machine-readable form:** [`inventory.json`](inventory.json). Every table below is
  rendered from it, and [`tools/check_security_inventory.py`](../tools/check_security_inventory.py)
  checks it (`task security:check`; see [What the checker enforces](#what-the-checker-enforces)).
- **This is an inventory, not a control.** It creates and changes no identity, account,
  key, token, service, firewall rule or permission. Nothing here makes the strong tier
  operational: that still waits for S-02.x (decision 0003, C6).

## How to read it

Every entry carries one status from a closed set:

| Status | Meaning | Must carry |
|---|---|---|
| `observed` | Exists today and is shown by committed evidence. | at least one evidence link: a committed evidence record, or the decision or profile that records the observation |
| `planned` | Defined by accepted authority (the blueprint, the plan, a decision or the execution-profile contract) but not built or not enforced yet. | at least one source link |
| `unknown` | Not established from the accepted records or the committed evidence. | a finding |
| `conflict` | Two accepted records disagree. | a finding of kind `conflict` |

Planned and observed are kept apart at two levels:

- **Principals** carry `identity.planned` (what the authority assigns) and
  `identity.observed` (what exists today, with evidence, or `none`). A principal can be
  `planned` while part of its identity is already observed: the engineering agent's
  container identity was observed for a no-LLM fixture conversation, but no agent
  workload has run.
- **Operations** carry the accountable `principal` the authority names, and, separately,
  who performs the operation today (`observed_performer`). An operation is `observed`
  only where the binding to its principal is itself shown by evidence; where the
  principal is planned and an interim performer acts today, the operation stays
  `planned`. Example: the authority gives conversation creation to the trusted
  dispatcher (`planned`), while today the Owner's account performs it through the
  operator login during inspection runs.

No conflict between accepted records was found. No credential or secret value was
encountered in the records read for this inventory; credentials are described by
custody only, and locations are described generically.

## Summary

- **Trust domains (9).** Owner; trusted management; privileged effect; Git hosting
  (trusted computing base); execution-guest control (contained); untrusted engineering;
  review; untrusted CI; CI runner host (contained).
- **Principals (17).** Six are observed today: the Owner, the Owner's Windows
  account, the host-side bootstrap agent sessions, and in the guest root, the service
  user `openhands` and the operator login `agent`. One, the release job environment, is
  unknown. The other ten are planned.
- **Credentials (21), assets (35), findings (15:** 9 unknown, 4 open risks, 2 limits).
- **Privileged operations (34), each with exactly one principal.** 6 Owner-only,
  all assigned to `owner`. 13 observed, 18 planned, 3 unknown. By principal:
  `management-dispatcher` 8 (the Agent Server management API, 2 of them unknown);
  `owner` 6; `owner-os-account` 5 (guest lifecycle, exec, exchange, session-key export,
  provisioning fetch); `guest-root` 3; `privileged-executor` 2;
  `guest-service-openhands` 1 (the guest's Docker API); and one each for `gitea-site-admin`,
  `engineering-agent`, `reviewer-agent`, `ci-job`, `ci-runner-service`,
  `release-job-environment` (unknown), `authorization-verifier`, `integration-service`
  and `inference-broker`.
- **No agent principal holds, manages or may read an Owner, admin, executor or
  management credential, and no Owner-only operation uses such a credential.** The
  engineering and reviewer agents and CI jobs hold only `scoped` credentials (their
  Gitea bot or job tokens, and each conversation's own inner-server keys).
- **The material limit** is [`fd-bootstrap-shared-identity`](#findings): the host-side
  bootstrap agents run as the Owner's Windows account, so every credential in that
  account's custody is reachable by them. They are recorded as an agent principal that
  shares the Owner's OS identity and is **not independently isolated** (decision 0004,
  Owner clarification 5). UAC consent gates their elevation but is not a security
  boundary. The checker requires every privileged credential they can reach this way to
  carry a finding that names them.

## Trust domains

| Domain | Trust | What it holds | Status |
|---|---|---|---|
| `td-owner` Owner | trusted | The Owner's identity and decisions, protected policy and the Owner's host account. Same-account shell access can defeat an otherwise sound approval design. | observed |
| `td-management` Trusted management | trusted | The minimal dispatch broker or restricted launcher, the Integration Service, the authorization verifier and the inference broker, on the trusted control side and never mounted into agent execution. | planned |
| `td-privileged-effect` Privileged effect | trusted | The restricted operation executor and its effect receipts, behind a separate OS credential boundary. | planned |
| `td-git-hosting` Git hosting | trusted-computing-base | The Gitea server, its host and its site administration. Gitea's protections do not survive compromise of its administrator or host. | planned |
| `td-guest-control` Execution guest control | contained | The managed Linux execution VM's own system: guest root, the outer Agent Server's service user and the guest's own Moby. The VM is a host-protection boundary; this domain holds the guest's Docker authority and must stay unreachable from untrusted engineering. | observed |
| `td-untrusted-engineering` Untrusted engineering | untrusted | Planner and builder agents, the ACP provider process and build or test workloads, each in a per-conversation container inside the guest. Assumed hostile. | planned |
| `td-review` Review | untrusted | Independent reviewer attempts: a separate session, runner or model and context from the builder; may review, never merge. | planned |
| `td-untrusted-ci` Untrusted CI | untrusted | CI jobs that execute pull-request code: no Owner, release or signing secret, no host Docker socket. | planned |
| `td-ci-runner-host` CI runner host | contained | A dedicated runner host, not the trusted management host, whose runner service registers with Gitea and launches disposable job environments. | planned |

Two Agent Servers appear in the records and belong to different domains. The **outer**
Agent Server runs in the guest as the service user `openhands`, holds the guest's Docker
authority and serves the management API (`td-guest-control`; decision 0003, F-04.1c
amendment: "the guest's own service principal"). Each conversation runs its own
**inner** Agent Server inside its container (`td-untrusted-engineering`; blueprint
`#containment-architecture`, "Per-conversation Agent Server").

## Principals and their identity mechanisms

| Principal | Kind / domain | Agent-controlled | Planned identity | Observed today | Status |
|---|---|---|---|---|---|
| `owner` The Owner | owner / `td-owner` | no | A separate Gitea Owner account, the only identity on the authorization branch's merge allowlist; privileged host acts by the Owner's interactive UAC approval of a specifically authorized operation. | The Owner directs the work through the Overseer; Owner decisions and authorizations are recorded in decisions/ and evidence/bootstrap-log.md; host acts A1 and A3 were approved by interactive UAC consent. No authenticated Owner authorization record exists yet. | observed |
| `owner-os-account` The Owner's Windows account | owner-host-account / `td-owner` | no | The Owner's own interactive account. It holds no executor or service identity, and no executor credential is stored in its Credential Manager. | Medium-integrity token, Administrators deny-only, no SeTakeOwnership/SeBackup/SeRestore, UAC on with secure-desktop consent. It runs QEMU as an ordinary user process (no service, no elevation) and owns the guest-state root, whose ACL holds only this account, SYSTEM and Administrators. | observed |
| `bootstrap-host-agents` Host-side bootstrap agent sessions | agent / `td-owner` | yes (shares `owner-os-account`; not isolated) | No independent identity is planned for them. Engineering work moves into the guest (td-untrusted-engineering) and privileged work to separate identities (the management service and the executor at G-04.2.1). | Claude Code sessions (Overseer, Architect, Builder) running as the Owner's Windows account. They are not independently isolated security principals; their elevation is gated only by the Owner's interactive UAC consent, which is not an OS security boundary, and they hold no standing elevation. | observed |
| `management-dispatcher` Trusted dispatcher and restricted launcher | trusted-service / `td-management` | no | The trusted dispatcher identity and network admitted to the Agent Server's create and admin routes (S-01.3.1). It alone holds the Agent Server session key and, through the Agent Server, Docker authority; it checks accepted Work, policy revision, mounts, network and resource budget before it starts a conversation. | none | planned |
| `integration-service` Integration Service | trusted-service / `td-management` | no | One lightweight local process for ordinary adapters, with its own identity; custody of integration.sqlite moves to it. It cannot write effect receipts. | none | planned |
| `authorization-verifier` Authorization verifier | trusted-service / `td-management` | no | A small read-only verifier: a webhook only wakes it; it reads the protected ref, the PR, merged_by, the exact blob and the policy, and never executes. | none | planned |
| `inference-broker` Inference broker | trusted-service / `td-management` | no | The host-side broker behind the guest's `inference` endpoint class: the only path to provider credentials, which never enter the guest. | none | planned |
| `privileged-executor` Privileged effect executor | executor / `td-privileged-effect` | no | A genuinely separate Windows identity created by Owner act A4 at G-04.2.1, preferably a service identity such as a virtual service account; Modify on the effects root only; it applies only typed, allowlisted effects. | none | planned |
| `release-job-environment` Release-signing or deployment job environment | trusted-service / unknown | no | Named only as a separately credentialed environment that runs narrowly authorized release or deployment jobs after verifying the protected revision. | none | unknown |
| `gitea-site-admin` Gitea site administrator | git-admin / `td-git-hosting` | no | The Gitea instance's site administrator. Can change protection rules and impersonate users, so it is in the trusted computing base and is never exposed to agents or CI. | none | planned |
| `engineering-agent` Engineering agent (planner and builder) | agent / `td-untrusted-engineering` | yes | A per-conversation container started by the guest's Agent Server Docker runtime: approved read-only definitions, a working copy only, a minimal tool set; a dedicated Gitea 28 token-only bot account with non-admin repository write and PR scope. No Owner, merge, admin, executor, Docker or guest-management credential. | Only the container identity is observed, for the no-LLM fixture conversation: uid:gid of the Agent Server's service user (999:989), cap-drop ALL, no-new-privileges, exactly three binds under the server's scratch, port 8000 published on the guest's loopback only, and its own per-conversation OH_SECRET_KEY and session key in its environment. No agent workload, LLM or repository content has run. | planned |
| `reviewer-agent` Reviewer agent | agent / `td-review` | yes | A separate session, runner or model and context from the builder; its own Gitea bot identity that can submit reviews but cannot merge, administer or reach the executor. | none | planned |
| `ci-job` CI job executing pull-request code | ci-job / `td-untrusted-ci` | yes | A disposable container or VM on the dedicated runner host, with a restricted Gitea job token; no host-mode execution, broad container socket, user home or Owner credential. | none | planned |
| `ci-runner-service` CI runner service | trusted-service / `td-ci-runner-host` | no | The runner daemon on the dedicated runner host. Its registration secret stays unreachable from the job filesystem. | none | planned |
| `guest-root` Guest root | guest-system / `td-guest-control` | no | Root inside the execution guest, reached only through cloud-init at create and declared systemd units. | Root SSH login is refused (PermitRootLogin no). Root acts only in the single-use provision step (triggered once by a host marker, consuming only seed-pinned sha256 values) and in two read-only facts reporters (at boot, and on demand at most 20 runs in 60 s). | observed |
| `guest-service-openhands` Guest service user `openhands` (outer Agent Server) | guest-system / `td-guest-control` | no | The guest's own service principal for the Agent Server: a system user with no login, in group docker, reaching only the guest's own daemon socket. | System user openhands (uid 999), shell nologin, password locked, groups openhands and docker; runs aieh-agent-server.service with NoNewPrivileges, an empty capability set, ProtectSystem=strict and IPAddressDeny=any except localhost; its process environment is readable only by itself and root. | observed |
| `guest-login-agent` Guest login user `agent` (operator login) | operator-login / `td-guest-control` | no | The guest's non-root login for operators and provisioning: exec is never offered to agents, who reach the guest only through the Agent Server path. | User agent (uid 1000), no sudo, not in group docker (connect to both daemon sockets: EACCES). SSH login only with the per-instance key over the host-loopback forward. Host tooling uses it for exec, exchange, the provisioning upload, the facts requests and the API probes, and it can read the Agent Server session key (root:agent 0440). | observed |

## Privileged operations

Each row names exactly one principal: the identity that the accepted authority makes
accountable for the operation. "Performed today by" records the interim performer seen
in the evidence.

| Operation | Mechanism | Principal | Owner-only | Credentials | Performed today by | Status |
|---|---|---|---|---|---|---|
| `op-as-conversation-create` Create a conversation | POST /api/conversations on the outer Agent Server | `management-dispatcher` | no | `cred-agent-server-session-key` | `owner-os-account` | planned |
| `op-as-runtime-stop` Stop a conversation's container | DELETE /api/conversations/{id}/runtime | `management-dispatcher` | no | `cred-agent-server-session-key` | `owner-os-account` | planned |
| `op-as-runtime-reprovision` Reopen a conversation's container | POST /api/conversations/{id}/runtime/reprovision | `management-dispatcher` | no | `cred-agent-server-session-key` | `owner-os-account` | planned |
| `op-as-conversation-delete` Delete a conversation and its data | DELETE /api/conversations/{id} | `management-dispatcher` | no | `cred-agent-server-session-key` | `owner-os-account` | planned |
| `op-as-conversation-pause` Pause a conversation's run | POST /api/conversations/{id}/pause (present in both documents; not used) | `management-dispatcher` | no | `cred-agent-server-session-key` | - | planned |
| `op-as-management-read` Read conversations, runtimes and events | GET /api/conversations/{id}, /search, /count, /{id}/runtime and events search | `management-dispatcher` | no | `cred-agent-server-session-key` | `owner-os-account` | planned |
| `op-as-unenumerated-routes` Other Agent Server management capabilities | Routes behind the advertised credential-binding, secret-grant, agent-launch, profile and skill capability families (not enumerated) | `management-dispatcher` | no | `cred-agent-server-session-key` | - | unknown |
| `op-child-conversation` Conversation creation requested from inside a conversation | The usable tool start_child_conversation (path to a server not established) | `management-dispatcher` | no | - | - | unknown |
| `op-moby-container-control` Run, inspect and remove containers | The guest Docker Engine API through /run/docker.sock | `guest-service-openhands` | no | `cred-moby-docker-group` | `guest-service-openhands` | observed |
| `op-moby-daemon-admin` Administer the guest's Moby daemon | daemon.json, containerd config, sysctl, image load and tag, by the root step | `guest-root` | no | - | `guest-root` | observed |
| `op-guest-provision` Provision the guest (single-use root step) | aieh-provision, triggered once by a host marker after the SFTP upload | `guest-root` | no | - | `guest-root` | observed |
| `op-guest-facts` Report root-only guest and container facts | aieh-docker-facts at boot; aieh-conversation-facts on an agent-created request file | `guest-root` | no | - | `guest-root` | observed |
| `op-guest-lifecycle` Guest lifecycle | tools/guest.py preflight, create, start, stop, destroy, recreate, inspect; qemu-img; QMP | `owner-os-account` | no | - | `owner-os-account` | observed |
| `op-guest-exec` Run a command in the guest | tools/guest.py exec: SSH as agent over the loopback forward (operators and provisioning only) | `owner-os-account` | no | `cred-guest-ssh-key` | `owner-os-account` | observed |
| `op-exchange` Exchange push and pull | Git bundles by SFTP over the management forward | `owner-os-account` | no | `cred-guest-ssh-key` | `owner-os-account` | observed |
| `op-session-key-export` Export the Agent Server session key to the host | tools/guest.py provision: SFTP as agent into the per-instance directory | `owner-os-account` | no | `cred-guest-ssh-key`, `cred-agent-server-session-key` | `owner-os-account` | observed |
| `op-provision-fetch` Fetch pinned provisioning artifacts on the host | tools/guest.py provision-fetch, including one pinned, checksum-verified crane run from the state directory | `owner-os-account` | no | - | `owner-os-account` | observed |
| `op-guest-boundary-change` Widen the guest boundary | Any guest network, guestfwd, host share, LLM credential, new host port or launch.argv change | `owner` | yes | - | `owner` | observed |
| `op-host-privileged-change` Privileged host change | Elevated host acts (A1 Windows feature, A3 guest-state root, A4 effects root and executor identity) | `owner` | yes | `cred-uac-consent` | `owner-os-account` | observed |
| `op-git-push-public` Push to the public repository | git push to the public GitHub origin, after the publication-safety gate | `owner` | yes | `cred-owner-github` | `owner-os-account` | observed |
| `op-policy-change` Change governance | The blueprint, accepted decisions, the plan, integrity-tracked files, the publication-safety gate and repository policy | `owner` | yes | - | `owner-os-account` | observed |
| `op-protected-merge` Authorize an operation by protected merge | Owner-only merge of an exact operation manifest into the protected authorization branch | `owner` | yes | `cred-gitea-owner-account` | - | planned |
| `op-gitea-administration` Administer Gitea | Branch protection, merge allowlists, bot accounts, token maxima, audit settings, impersonation | `gitea-site-admin` | no | `cred-gitea-admin` | - | planned |
| `op-open-proposal-pr` Push a proposal branch and open a PR | Gitea API or git push with the builder's bot token | `engineering-agent` | no | `cred-gitea-bot-builder` | - | planned |
| `op-submit-review` Submit an independent review | Gitea review with the reviewer's bot token | `reviewer-agent` | no | `cred-gitea-bot-reviewer` | - | planned |
| `op-ci-untrusted-job` Execute a pull-request CI job | A Gitea Actions job on the dedicated runner host | `ci-job` | no | `cred-ci-job-token` | - | planned |
| `op-ci-runner-registration` Register a runner and receive jobs | The runner service with its registration secret | `ci-runner-service` | no | `cred-runner-registration` | - | planned |
| `op-release-signing-deploy` Sign a release or run a deployment job | A narrowly authorized job after verification of the protected revision | `release-job-environment` | no | - | - | unknown |
| `op-authorization-verify` Verify an Owner authorization | Read-only lookup of the protected ref, PR, merged_by, blob and policy | `authorization-verifier` | no | `cred-verifier-read` | - | planned |
| `op-effect-apply` Apply an authorized external effect | The restricted executor: typed, allowlisted operation kinds; target and precondition recheck; one-time effect key | `privileged-executor` | no | `cred-executor-identity`, `cred-executor-target-secrets` | - | planned |
| `op-effect-receipt-write` Write effect receipts | effects.sqlite under OS-enforced custody | `privileged-executor` | no | `cred-executor-identity` | - | planned |
| `op-effect-store-custody` Create the effect store's custody, or restore the store | A4 (effects root, executor principal) and each restore, as elevated Owner acts with the executor stopped | `owner` | yes | `cred-uac-consent` | - | planned |
| `op-integration-store-write` Write the integration store | integration.sqlite: coordination receipts and rebuildable projections | `integration-service` | no | - | - | planned |
| `op-inference-call` Call a model provider | The brokered inference endpoint; the provider credential stays with the broker | `inference-broker` | no | `cred-llm-provider-key` | - | planned |

Agent Server routes are listed only as far as the committed evidence records them: the
Docker-runtime lifecycle routes of the locked 1.60.1 wheel (`docker_runtime/routers.py`,
confirmed in the running server's own `/openapi.json`), and the unauthenticated
`/server_info`, `/alive` and `/openapi.json`. The capability families that `/server_info`
also advertises are inventoried as one unknown asset and operation
(`op-as-unenumerated-routes`); no route is invented for them.

## Credential requirements

Authority classes: `owner`, `admin`, `executor` and `management` are privileged and are
never held, managed or readable by an agent principal; `scoped`, `guest-local` and
`provider` are not privileged. `external:` marks an issuer outside the inventory.

| Credential | Authority | Issuer | Holder (manager) | Also readable by | Storage and custody | Scope | Lifetime | Rotation and revocation | Status |
|---|---|---|---|---|---|---|---|---|---|
| `cred-uac-consent` The Owner's interactive UAC consent | owner | `owner` | `owner` (`owner`) | - | Not stored: an interactive secure-desktop approval of one specifically authorized elevated operation that an agent may initiate. | One elevated host operation (A1, A3, A4 and effects-store restore). | One operation. | `owner` | observed |
| `cred-owner-github` The Owner's push credential for the public GitHub repository | owner | `external:github` | `owner-os-account` (`owner-os-account`) | - | The Owner's host credential store or key (not inspected). | Push to the public repository; publication. | Unknown. | `owner` | unknown |
| `cred-owner-provider-login` The Owner's coding-assistant login used by the host-side agent sessions | provider | `external:model-provider` | `owner-os-account` (`owner-os-account`) | - | The coding assistant's own login storage in the Owner's account (not inspected). | Model access under the Owner's provider account; it grants no approval, merge, policy or privileged host authority in this system. | Unknown. | `owner` | unknown |
| `cred-guest-ssh-key` Per-instance SSH key for the guest operator login | management | `owner-os-account` | `owner-os-account` (`owner-os-account`) | - | The per-instance directory under the guest-state root (ACL: the Owner's account, SYSTEM, Administrators); never ~/.ssh. Generated at create with the system ssh-keygen. | SSH and SFTP as guest user agent over the host-loopback forward: exec, exchange, provisioning upload and session-key export. | The instance: destroy removes it; recreate issues a new one. | `owner-os-account` | observed |
| `cred-guest-host-keys` Guest SSH host keys | guest-local | `guest-root` | `guest-root` (`guest-root`) | - | Inside the guest; the fingerprints reach the host from cloud-init's serial-log block into the instance's known_hosts. | Host authentication of the guest's sshd. | Regenerated at every create. | `guest-root` | observed |
| `cred-agent-server-session-key` Agent Server session API key (OH_SESSION_API_KEYS_0) | management | `guest-root` | `guest-service-openhands` (`guest-root`) | `guest-login-agent`, `owner-os-account` | Generated in the guest by the root step into a root-only environment file read by systemd; an agent-readable copy (root:agent 0440 in a root:agent 0750 directory); exported by SFTP as agent into the per-instance directory on the host. Records carry fingerprints only. | Every /api/* route of the outer Agent Server: one key, no per-route scope. | From provisioning until destroy; unchanged by a guest restart; new on recreate. | `owner-os-account` | observed |
| `cred-oh-secret-key` Agent Server OH_SECRET_KEY | guest-local | `guest-root` | `guest-service-openhands` (`guest-root`) | - | Root-only environment file in the guest (root:root 0600); never leaves the guest; searched for on the host by fingerprint only. | Encryption of the server's stored secrets and runtime-control key material. | From provisioning until destroy. | `guest-root` | observed |
| `cred-conversation-keys` Per-conversation OH_SECRET_KEY and session key | scoped | `guest-service-openhands` | `engineering-agent` (`guest-service-openhands`) | `guest-service-openhands`, `guest-root` | Passed by the Docker runtime as environment values into the conversation container; visible to anyone with Docker access (openhands and root); facts reports carry names only. | That conversation's own inner Agent Server. | The conversation container. | `guest-service-openhands` | observed |
| `cred-moby-docker-group` Membership of the guest's docker group | admin | `guest-root` | `guest-service-openhands` (`guest-root`) | - | Group membership: /run/docker.sock is root:docker 0660; containerd's socket is root:root 0660; no Moby TCP listener. | The guest's Docker Engine API, which is root-equivalent inside the guest. | The provisioned guest. | `guest-root` | observed |
| `cred-gitea-owner-account` The Owner's Gitea account | owner | `gitea-site-admin` | `owner` (`owner`) | - | The Owner's own login to the non-administrator Gitea account aieh-owner, created by gitea admin user create with --must-change-password. The final password is set by the Owner at first sign-in and exists only as Gitea's password hash. The temporary first-login password is held only in the Owner account's Windows Credential Manager ("AIEH Gitea owner (temporary)") until task gitea:finish-first-login deletes it. Never an Owner PAT or session inside agent workspaces or CI runners. | Merge allowlist of the protected authorization branch; review of exact operation manifests. | Temporary password: until the first sign-in and finish-first-login. Final password: not defined yet. | `owner` | observed |
| `cred-gitea-admin` Gitea site-administrator credential | admin | `external:gitea-installation` | `gitea-site-admin` (`gitea-site-admin`) | - | The Gitea site-administrator account aieh-site-admin, created by gitea admin user create with --must-change-password. Its final password is set by the Owner at first sign-in and exists only as Gitea's password hash in its database. The temporary first-login password, generated by Gitea, is held only in the Owner account's Windows Credential Manager (generic entry "AIEH Gitea site-admin (temporary)") until task gitea:finish-first-login deletes it. Never exposed to agents or CI. | Site administration, protection rules, impersonation. | Temporary password: until the first sign-in and finish-first-login. Final password: not defined yet. | `owner` | observed |
| `cred-gitea-bot-builder` Engineering agent's Gitea bot token | scoped | `gitea-site-admin` | `engineering-agent` (`management-dispatcher`) | - | Agent-visible environment only, provisioned per attempt by the credential broker. | Non-admin repository write and PR on the proposal branch; no merge, admin, protection, credential or executor privilege. | One attempt where the pinned Gitea supports attempt-bounded tokens, otherwise rotated at attempt end (S-01.2.1; to verify at S-01.2.2). | `management-dispatcher` | planned |
| `cred-gitea-bot-planner` Planning agent's Gitea bot token | scoped | `gitea-site-admin` | `engineering-agent` (`management-dispatcher`) | - | Agent-visible environment only, delivered per attempt by the dispatcher; never in an image, seed, repository, log or record. | Read the repositories in scope, push work/* proposal branches and open PRs whose writes are planning artefacts only (path-level realization pending the planning-artefact layout); no merge, protected-ref push, admin, protection, Work-status, executor, session-key or Docker privilege. | One attempt where the pinned Gitea supports attempt-bounded tokens, otherwise rotated at attempt end (S-01.2.1; to verify at S-01.2.2). | `management-dispatcher` | planned |
| `cred-gitea-bot-reviewer` Reviewer agent's Gitea bot token | scoped | `gitea-site-admin` | `reviewer-agent` (`management-dispatcher`) | - | The reviewer session's environment only. | Read the PR and submit a review; no merge, push to protected refs, admin or executor privilege. | One attempt where the pinned Gitea supports attempt-bounded tokens, otherwise rotated at attempt end (S-01.2.1; to verify at S-01.2.2). | `management-dispatcher` | planned |
| `cred-ci-job-token` CI job token (GITEA_TOKEN) | scoped | `external:gitea-actions` | `ci-job` (`ci-runner-service`) | - | The job environment, with restricted repository and workflow token maxima. | The consuming repository's job context; no protected merge, deploy or executor access. | One job. | `gitea-site-admin` | planned |
| `cred-runner-registration` CI runner registration secret | management | `gitea-site-admin` | `ci-runner-service` (`ci-runner-service`) | - | The runner host, unreachable from the job filesystem. | Register the runner and receive jobs. | Not defined yet. | `owner` | planned |
| `cred-verifier-read` Authorization verifier's read-only Gitea credential | scoped | `gitea-site-admin` | `authorization-verifier` (`authorization-verifier`) | - | The verifier's own identity; unreachable from code runners. | Read the protected authorization ref, PRs, merged_by and blobs. | Not defined yet. | `gitea-site-admin` | planned |
| `cred-executor-identity` Executor service identity | executor | `owner` | `privileged-executor` (`privileged-executor`) | - | A Windows service identity (a virtual service account preferred) with no stored password; never in the Owner's Credential Manager, never runas /savecred, never given to an agent. | Modify on the effects root; allowlisted effect kinds only. | Until the Owner revokes it. | `owner` | planned |
| `cred-executor-target-secrets` Executor target credentials | executor | `owner` | `privileged-executor` (`privileged-executor`) | - | Separately credentialed, encrypted; unreachable from agents, CI and the Integration Service. | The targets of allowlisted operation kinds; not defined until G-04.2.x. | Not defined yet. | `owner` | planned |
| `cred-llm-provider-key` Brokered model-provider credential | provider | `external:model-provider` | `inference-broker` (`inference-broker`) | - | Host side, behind the brokered `inference` endpoint; never in the guest, the seed, a container or an agent-readable file. | Model inference for engineering conversations. | Not defined yet. | `owner` | planned |
| `cred-owner-ui-access` Owner UI access to the Agent Server and Integration Service | management | `external:undefined` | `owner` (`owner`) | - | Not defined. | Agent Canvas reaches only the backend needed for an Owner-authorized engineering session. | Not defined. | `owner` | unknown |

## Asset inventory

Hosts, guests, processes, sockets, listeners, APIs, durable stores and repositories.
`{ssh_port}` and `{qmp_port}` are the free loopback ports chosen at `create`.

| Asset | Kind | Custodian | Location and protection | Status |
|---|---|---|---|---|
| `host-owner-windows` The Owner's Windows host | host | `owner-os-account` | The trusted Owner host: Windows 11 Home, WHPX enabled (A1), the pinned QEMU (A2). | observed |
| `host-credential-stores` The Owner's host credential stores | credential-store | `owner-os-account` | The Owner's credential stores (protected for this leaf; not listed or read). | unknown |
| `host-guest-state-root` Guest-state root | directory | `owner-os-account` | The directory the Owner designated by act A3, outside the checkout and the Owner profile; ACL: the Owner's account, SYSTEM, Administrators. It holds the images, the pinned provider, the provision stage and the instances. | observed |
| `host-instance-directory` Per-instance directory | directory | `owner-os-account` | One directory per guest under the guest-state root: disks, seed, launch record, serial log, the SSH key and known_hosts, the exported session key, exchange staging. destroy removes it. | observed |
| `host-qemu-process` QEMU process | process | `owner-os-account` | An ordinary user process of the Owner's account: no service, no elevation. The strong tier buys a kernel boundary, not a principal boundary. | observed |
| `listener-host-ssh-forward` Host loopback SSH forward | listener | `owner-os-account` | Host 127.0.0.1:{ssh_port} to guest :22 (hostfwd); classes management and exchange. Reachable by any local process; authentication by the per-instance key. | observed |
| `listener-host-qmp` QMP monitor | listener | `owner-os-account` | Host 127.0.0.1:{qmp_port}, loopback TCP chardev, unauthenticated; host-only (refused from the guest). Full VM control. | observed |
| `guest-execution-vm` Strong execution guest | guest | `owner-os-account` | Debian 13 under QEMU/WHPX (profile strong-windows-qemu-whpx): SLIRP restrict=on, ipv6=off, no host share, no guestfwd. The strong tier is not operational until S-02.x passes (C6). | observed |
| `guest-exchange` Repository exchange | directory | `guest-login-agent` | The guest's exchange directory and its host staging: git bundles only, bounded in size; pull never writes into the Owner's repositories. | observed |
| `guest-sshd` Guest sshd | listener | `guest-root` | Base-image sshd on 0.0.0.0:22 and [::]:22 in the guest; root login refused. | observed |
| `guest-agent-server-listener` Outer Agent Server listener | listener | `guest-service-openhands` | The guest's 127.0.0.1:8000 only (explicit --host 127.0.0.1); class management, guest-local; not forwarded to the host (the Agent Server host forward is deferred). | observed |
| `guest-conversation-listeners` Conversation container listeners | listener | `guest-service-openhands` | One docker-proxy listener per running owned container on the guest's 127.0.0.1 at an ephemeral port, mapped to the container's port 8000; never forwarded to the host. | observed |
| `guest-moby-socket` Guest Docker daemon socket | socket | `guest-root` | /run/docker.sock, root:docker 0660; agent gets EACCES; never mounted into a conversation container. | observed |
| `guest-containerd-socket` Guest containerd socket | socket | `guest-root` | /run/containerd/containerd.sock, root:root 0660; the CRI plugin is off, so no streaming listener. | observed |
| `guest-secrets-env-file` Agent Server secrets environment file | secret-file | `guest-root` | /etc/aieh/agent-server/secrets.env, root:root 0600; agent gets EACCES. | observed |
| `guest-session-key-file` Agent-readable session key file | secret-file | `guest-root` | /var/lib/aieh/agent-server/session.key, root:agent 0440, in a root:agent 0750 directory. | observed |
| `guest-provision-root-step` Single-use root provisioning step | privileged-unit | `guest-root` | aieh-provision.path and .service, seeded by cloud-init: triggered once by a host marker; copies, verifies against seed-pinned sha256 values, installs with native tools, deletes the upload and disables itself. | observed |
| `guest-facts-reporters` Root read-only facts reporters | privileged-unit | `guest-root` | aieh-docker-facts (every boot) and aieh-conversation-facts (on demand: agent creates a request file in a root:agent 0730 directory; the reporter removes it unread, runs docker ps and container inspect only, redacts secret values; at most 20 runs in 60 s, then fails closed until the next boot). | observed |
| `conversation-container` Conversation container | container | `guest-service-openhands` | One per Docker conversation: the locked image ID, three binds under the server's scratch, cap-drop ALL, no-new-privileges, the server's uid:gid, Moby's default bridge with host.docker.internal mapped to the guest's docker0. Its inner server also starts VSCode on port 8001 inside its network namespace. | observed |
| `api-agent-server-management` Outer Agent Server management API | api | `guest-service-openhands` | /api/* on the guest's 127.0.0.1:8000; X-Session-API-Key required (401 without it or with a wrong key). Recorded routes: POST /api/conversations; GET /api/conversations/{id}, /search, /count; GET, DELETE /api/conversations/{id}/runtime; POST /api/conversations/{id}/runtime/reprovision; DELETE /api/conversations/{id}; events search; POST /api/conversations/{id}/pause (present, not used). | observed |
| `api-agent-server-public` Outer Agent Server unauthenticated routes | api | `guest-service-openhands` | /server_info, /alive and /openapi.json answered without the key on the guest loopback; read only. | observed |
| `api-agent-server-unenumerated` Further Agent Server capabilities | api | `guest-service-openhands` | Capability families advertised by /server_info at 1.60.1 whose routes are not recorded: credential_binding_v1 (with readiness probe and activation guard), profile_secret_scope_v1, canvas_app_backend_secret_grants_v1, canvas_app_backend_enable_lifecycle_v1, agent_launch_pipeline_v1, agent_profile_draft_materialize_v1, profile_persona_v1, profile_public_skills_v1, skill_catalog_v1, tool_catalog_v1; and the usable tool start_child_conversation. | unknown |
| `api-moby` Guest Docker Engine API | api | `guest-root` | Over /run/docker.sock only; reached by the server's docker CLI as openhands. | observed |
| `store-agent-server-scratch` Agent Server data on guest scratch | store | `guest-service-openhands` | /srv/scratch/openhands: conversations, persistence (runtime-control with encrypted key material, runtime-data with workspaces), home and tmp; owner openhands, 0711/0700. | observed |
| `store-moby-data-root` Moby data root | store | `guest-root` | /srv/scratch/docker, root-only; never a conversation mount source. | observed |
| `store-effects` Privileged effect store (effects.sqlite) | store | `privileged-executor` | An explicit, Owner-designated root on a local fixed volume outside the repository, every profile, the guest-state root and the integration tree. Interim custody: owner Administrators, DACL SYSTEM and Administrators only; the executor added as one Modify entry at A4. | planned |
| `store-integration` Integration store (integration.sqlite) | store | `owner-os-account` | Default per-user location under the local application-data folder; Owner-session custody during bootstrap; custody moves to the Integration Service identity later. | planned |
| `repo-owner-local` The Owner's local repositories | repository | `owner-os-account` | This checkout and the Owner's other durable repositories on the host; never mounted into a guest, never written by exchange pull, never deleted automatically. | observed |
| `repo-github-public` Public GitHub repository | repository | `owner` | The public origin of this repository; protected by the publication-safety gate before commit and push. | observed |
| `gitea-server` Gitea server | service | `gitea-site-admin` | Gitea 28.3.0, the pinned Windows binary (composition/lock/components.lock.json), as a host-loopback service: HTTP on 127.0.0.1:13300 only, plus Gitea's built-in egress-policy proxy on a kernel-assigned 127.0.0.1 port. It runs as the Owner's Windows account without elevation, inside a supervisor's kill-on-close Job Object (integrations/gitea/gitea_host.py). Its binary is an asset in the managed data root's assets/release-binaries/gitea/28.3.0/, its configuration and SQLite state are in persistent/gitea/ and its logs in persistent/logs/gitea/ (default root %LOCALAPPDATA%\AIEH). Sign-in is required, registration is disabled, there is no SSH server, and it runs offline. | observed |
| `repo-gitea-authorization` Gitea authorization repository | repository | `owner` | A dedicated repository with one protected authorization branch; operations/<operation-id>.json manifests; Owner-only merges; no direct or force pushes; merge commits only. | planned |
| `repo-gitea-policy` Gitea protected policy and workflow-source repositories | repository | `owner` | Protected governance repositories: policy profiles, the agent and skill catalog, central scoped workflows. | planned |
| `ci-runner-host` Dedicated CI runner host | host | `ci-runner-service` | Not the trusted management host; untrusted jobs in disposable containers or VMs; no host-mode execution or broad container socket. | planned |
| `endpoint-inference` Inference endpoint class | listener | `inference-broker` | A guestfwd to a host-side broker on 127.0.0.1; deferred: the broker does not exist and enabling a guestfwd needs separate Owner authorization. | planned |
| `endpoint-provision` Provision endpoint class | listener | `owner-os-account` | A phase-limited guestfwd to an allowlisting proxy; deferred and unused (provisioning uses the SFTP channel instead). | planned |

### Open risks against the assets they affect

The containment deviations recorded at F-04.2 are not resolved here; they belong to
S-01.3.x and E-01.2.2:

- **`host-gateway`, the default bridge and request caps that override the server's**
  affect `conversation-container`, `guest-sshd` and `guest-conversation-listeners`
  (`fd-container-network-deviations`).
- **Conversation containers run as the service user's uid** and their keys are visible
  through `docker inspect` (`fd-container-shares-service-uid`).
- **QMP and the SSH forward** are open to every local process on the host
  (`fd-host-loopback-exposure`).

## Findings

- **`fd-bootstrap-shared-identity`** (limit): Host-side bootstrap agents share the Owner's Windows account. The host-side agent sessions run as the Owner's account and are not independently isolated security principals. Every credential and store in that account's custody (the public-repository push credential, the provider login, the guest SSH keys, the exported session keys, QMP, the guest-state root, the integration store) is reachable by them. Their elevation is gated by the Owner's interactive UAC consent, which is not an OS security boundary. This is the accepted bootstrap limit; the guest boundary is the boundary against untrusted agents, and the genuine OS boundary for privileged effects is the executor's separate identity (G-04.2.1). No credential is designated to an agent principal here; the reachability is disclosed, not prevented. Since F-06.1 this includes the host-loopback Gitea: any process of the Owner's account, host agents included, can read Gitea's app.ini secrets (SECRET_KEY, INTERNAL_TOKEN, JWT_SECRET) and its SQLite database under the managed data root. The INTERNAL_TOKEN reaches Gitea's private API, and write access to the database can change any account, its administrator flag or its password hash, so such a process can forge or take over Gitea sessions and identities, the site administrator's and the Owner account's included. Until task gitea:finish-first-login, the two temporary first-login passwords in Credential Manager are readable the same way. The final passwords exist only as Gitea's password hashes. Directory placement is not a security boundary (decision 0009, point 11). Carried to: S-01.2.1, S-01.2.2, G-04.2.1.
- **`fd-owner-authorization-record`** (limit): Owner authorization has no authenticated record yet. During bootstrap the Owner's decisions and authorizations reach the repository as records the Overseer writes (decisions/, evidence/bootstrap-log.md), committed from the Owner's account. The planned record is an Owner-only protected Gitea merge, verified by a read-only verifier (SEC-02). Gitea runs on host loopback (F-06.1), but no authorization repository or protected branch exists yet. Carried to: G-04.x.
- **`fd-guest-login-name-and-key`** (unknown): The guest login named `agent` is an operator login that holds the management key. The contract makes the guest user `agent` the operators' and provisioning login (exec is never offered to agents) and lets it read the Agent Server session key (P5 as amended at F-04.1). The same user is the unprivileged vantage of the P6 negative checks, and its name collides with the engineering-agent role. If any untrusted workload were ever given this login, it would hold the full management API key and could create conversations, against S-01's proof. Whether the management key stays readable by the login user once a dispatcher exists is not decided by any accepted record: it belongs to S-01.3.1. Carried to: S-01.3.1, S-01.3.2.
- **`fd-session-key-not-fine-grained`** (open-risk): One session key grants the whole management API. The outer Agent Server accepts one X-Session-API-Key for every /api/* route; there is no per-route or per-role scope, and the only rotation is recreate and provision. The blueprint warns not to assume a session API key is a fine-grained permission token and to keep the broad management API behind the trusted execution network. Carried to: S-01.2.1, S-01.3.1.
- **`fd-agent-server-route-inventory`** (unknown): The Agent Server's privileged routes are only partly enumerated. Committed evidence records the Docker-runtime lifecycle routes (from the locked wheel's docker_runtime/routers.py and the running server's /openapi.json) and the unauthenticated /server_info, /alive and /openapi.json. /server_info also advertises capability families (credential binding, secret scopes and grants, agent launch pipeline, profiles, skills and tools) whose routes are not recorded. The release openapi.json documents the local runtime only and is not committed (decision 0005). No routes are invented here; S-01.3.1 must enumerate them from the locked artefacts. Carried to: S-01.3.1.
- **`fd-child-conversation-tool`** (unknown): An agent tool can start child conversations. The server's usable_tools include start_child_conversation. Whether an agent inside a conversation can thereby cause conversation creation, and on which server and with which credential, is not established by the committed evidence. S-01's proof requires that an agent cannot invoke privileged conversation creation. Carried to: S-01.3.1, S-01.3.2, E-01.2.2.
- **`fd-container-network-deviations`** (open-risk): Conversation containers keep upstream network defaults. Recorded deviations: --add-host host.docker.internal:host-gateway (the guest's docker0), Moby's default bridge instead of --network none, and create-request caps that replace the server's without an upper bound. Inference, not observed: from a container, the guest's sshd (bound to all addresses) is reachable at the docker0 address, and other conversation containers' inner servers (port 8000, and VSCode on 8001) are reachable across the default bridge. Not tested; carried. Carried to: S-01.3.1, S-01.3.2, E-01.2.2, S-02.1.
- **`fd-container-shares-service-uid`** (open-risk): Conversation containers run as the Agent Server's service uid. The Docker runtime starts each container with --user of the server's uid:gid (openhands, 999:989), the principal that is in group docker. The separation of the untrusted workload from the server rests on the container's namespaces, cap-drop ALL, no-new-privileges and the absent socket mount, with no user-namespace remap. Each conversation's keys are environment values visible to openhands and root through docker inspect. Carried to: S-01.3.2, S-02.1.
- **`fd-host-loopback-exposure`** (open-risk): Host loopback control surfaces are open to every local process. QMP is an unauthenticated loopback TCP socket with full VM control, and the SSH forward is a loopback port protected by the per-instance key. Both are reachable by any local process of any user on the host: disclosed, not prevented (the standard library has no AF_UNIX on Windows). Carried to: S-01.4.
- **`fd-release-job-principal`** (unknown): No accepted record names the release-signing and deployment principal. The blueprint reserves persistent release credentials for 'separate, narrowly authorized jobs' in 'a separately credentialed environment', and also lists the runner and the privileged executor among the build and deploy tools. No accepted record says whether release signing and deployment run as the privileged executor, as a dedicated trusted runner, or as something else. The inventory names the role only as an unknown placeholder principal and does not decide it. S-01.2.1 narrows it without deciding it (decision 0007, Proposed): the principal is on the trusted side only, never ci-job or any agent role; its credential is of a privileged class; activation goes through op-effect-apply; and the signing identity is distinct from the executor's effect identity unless Q-02.4 decides otherwise. Q-02.4 and G-04.2.1 decide it. Carried to: S-01.2.1, Q-02.4, G-04.2.1.
- **`fd-ci-runner-unpinned`** (unknown): No CI runner is selected or pinned. composition/ pins Gitea but no runner. The runner's identity, its dedicated host, its isolation of jobs and the job-token maxima are planned only. Carried to: S-01.2.1, S-01.4.
- **`fd-gitea-version-docs`** (unknown): Gitea bot and token behaviour is unverified at the pinned version. The blueprint's SEC-02 qualification cites Gitea 28 token-only bot accounts and audit logging and names 28.2.0 as its baseline; composition/ pins 28.3.0, whose OpenAPI document was not retrieved. Bot-account and token-scope behaviour at 28.3.0 cannot be confirmed offline. Carried to: S-01.2.1, S-01.2.2.
- **`fd-owner-ui-access`** (unknown): The Owner UI's access to the Agent Server is not defined. Agent Canvas is to reach only the backend needed for an Owner-authorized engineering session, but no accepted record says which credential it uses or whether it would hold the management key. The Agent Server host forward is deferred (decision 0006). Carried to: S-01.3.1.
- **`fd-owner-credential-custody`** (unknown): Custody of the Owner's own credentials was not inspected. Credential stores are protected for this leaf, so the storage, scope and lifetime of the Owner's push credential and provider login are not established. Their existence is evident from the recorded pushes and headless runs. Carried to: S-01.2.2.
- **`fd-acp-provider-auth`** (unknown): How an engineering agent's coding provider authenticates is not defined. The ACP provider's default session mode is bypassPermissions, so it cannot be the isolation boundary. Provider credentials may only sit behind the brokered inference endpoint, which is deferred; how the provider inside a conversation container authenticates without holding an Owner or long-lived credential is not yet specified. S-01.2.1 fixes that no provider credential is ever a role token: the inference broker alone issues per-attempt inference access. No plan leaf owns the broker (a plan gap routed to the Owner). Carried to: S-01.2.1, S-02.x.

## What the checker enforces

`python -I -B tools/check_security_inventory.py` (`task security:check`) exits 0 only
when:

1. every privileged operation names exactly one principal (`principal` is one id, never
   a list) and that principal exists;
2. no credential of authority `owner`, `admin`, `executor` or `management` is held,
   managed or readable by an agent-controlled principal; an `owner` credential is held
   by a principal with Owner authority; and no Owner-only operation uses a credential
   that an agent principal holds, manages or may read;
3. an Owner-only operation's principal holds Owner authority; an agent principal is
   never assigned an Owner-only operation or a privileged credential; and only the
   Owner and the Owner's own account (never an agent-controlled principal) are
   described as holding Owner authority;
4. an agent principal that shares the OS identity of an Owner-authority principal is
   marked `independently_isolated: false` and carries a finding, and every privileged
   credential it can reach that way carries a finding that names it;
5. every referenced id exists: trust domains, principals, credentials, assets,
   findings, and plan leaves in `carried_to`;
6. every entry's status is one of the four, with its required evidence, sources or
   finding; every link resolves to a file in the repository, and every blueprint anchor
   and plan id to an element of it;
7. no machine path (drive letter, UNC path, user-profile variable) appears anywhere;
8. this README names every operation and finding id.

`--list` also prints each privileged operation with its principal and status. The
negative cases (an unnamed principal, an agent-held Owner token, a dangling reference,
and the rules above) are in
[`tools/tests/test_check_security_inventory.py`](../tools/tests/test_check_security_inventory.py).

## Sources

- Blueprint: `#security`, `#containment-architecture`, `#authorization-qualification`,
  `#governance-architecture`, `#quality-pipeline`, `#execution-qualification`,
  `#architecture`, `#integration-contracts`, `#control-evidence`, `#authority`.
- Plan: S-01, S-01.1, S-01.2.1, S-01.2.2, S-01.3.1, S-01.3.2, S-01.4.
- Decisions: [0001](../decisions/0001-agent-server-dispatch-precondition-and-version-line.md),
  [0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md),
  [0004](../decisions/0004-privileged-effect-store-custody-and-restore-semantics.md),
  [0005](../decisions/0005-distribution-model-upstream-download-no-redistribution.md),
  [0006](../decisions/0006-guest-provisioning-channel-and-image-conformance.md).
- Contract and profile: [`profiles/README.md`](../profiles/README.md),
  [`profile.json`](../profiles/strong-windows-qemu-whpx/profile.json),
  [`provision.lock.json`](../profiles/strong-windows-qemu-whpx/provision.lock.json).
- Evidence: [`bootstrap-log.md`](../evidence/bootstrap-log.md), F-03.2.2a, F-03.2.2b,
  F-03.3.1, F-03.3.2, F-03.4, F-04.1a, F-04.1b, F-04.1c, F-04.2 and F-05.2 under
  [`evidence/`](../evidence/).
- Role-token matrix and revocation contract (S-01.2.1): [`policy/`](../policy/README.md),
  which sets every rotation and revocation owner above.
- Components: [`composition/candidates.json`](../composition/candidates.json) (Gitea
  28.3.0; no CI runner pinned).
