# OA-03: upstream report on the Agent Server's start-up resume of stored `running` conversations

- **Date:** 2026-11-10 (UTC).
- **Status: draft, ready for the Owner's decision. Not filed.** Nothing was posted, commented,
  reacted to or opened upstream. Filing is an external publication and needs the Owner's
  authorization (OA-03).
- **Subject:** finding F-2 of E-01.2.2 (slice (b), compensated in slice (c)) and the recorded
  limit `fd-outer-server-local-recovery` (`security/inventory.json`), carried to decision 0001's
  version line.
- **Recommendation:** file a new report. No equivalent upstream issue or PR was found (section 3).
  The repository has no `SECURITY.md`, but its Security tab offers "Report a vulnerability", and
  its own bug umbrella (#5653) says that "security-relevant findings are handled separately". So
  the suggested route is GitHub's private vulnerability report, with the text in section 4. The
  text is also written to be safe as a public issue if the Owner prefers that route. The Owner
  decides the route.

## 1. Evidence review

### 1.1 What was observed (our evidence)

All of it comes from the pinned 1.60.1 outer Agent Server (release binary) in Docker runtime mode,
on disposable guests, with no LLM and no model credential.

| # | Observation | Source |
|---|---|---|
| O1 | With `base_state.json` `execution_status` set from `idle` to `running` (by the drill helper, runtime stopped), the next server start ran the resume path for the conversation **in the outer process**. Its journal had `ERROR error_recovering_running_conversation` at `conversation_service.py:2272`. It wrote a state event into the conversation's `events/`, and the outer view reported the conversation `running`. The exception text was not kept. Inference: the stored working directory is the container path `/workspace`, which the unit's `ProtectSystem=strict` keeps read-only. | `E-01.2.2b-live-drills.md` s4.2, #120 |
| O2 | With `running` plus `meta.json` `workspace.working_dir` set to a new path (the "start-up pair"), the outer server: logged `Failed to initialize git repository at <path>` (git is absent in the guest), `Resumed conversation <id> from persistent storage` and `Confirmation policy set to: kind='NeverConfirm'`; **created the path** (owner = the service uid, mode `700`, outside every container mount); took the conversation's owner lease (`owner_lease.json`); appended a state event; and left the status `error`. The same lines appeared on a second (exploration) guest. | `E-01.2.2b-live-drills.md` s4.2, #135 |
| O3 | The workload inside the container (uid 999, gid 989) wrote the pair itself through its own conversation bind. After a normal runtime stop (`DELETE …/runtime`, 204), `running` survived; the inner server's shutdown restored `working_dir` to `/workspace`. At the next outer start the resume path ran. | `E-01.2.2b-live-drills.md` s4.4 |
| O4 | After a forced kill of the container (`docker kill -s KILL`, no inner shutdown), both `running` and the `working_dir` text persisted. | `E-01.2.2c-fix-requalification.md` s4.1, variant B2 (F-11) |
| O5 | Once, after the outer server had resumed a record, the outer lease stayed in the directory and the conversation's own inner server then answered 404 for it. | `E-01.2.2b-live-drills.md` s8, F-7 |
| O6 | The created container (image, mounts, caps, user, `WorkingDir`, keys) was unchanged in every cycle, the steering ones included. 134 of 136 single-field alterations changed nothing. | `E-01.2.2b-live-drills.md` s4.2 |
| O7 | With our root pre-start quiesce step (it removes every container, then rewrites stored `running` to `error`), no resume, no path and no lease change occurred, in every variant, including a server SIGKILLed with its container alive and the workload rewriting the pair every 0.2 s. | `E-01.2.2c-fix-requalification.md` s4.1, s4.2 |

**Not observed:**
- the import of stored `tool_module_qualnames`: no drill set that field together with `running`;
- the registration of client tools or agent definitions;
- a resume of a conversation that was genuinely mid-run (no LLM ever ran);
- any hook, plugin or MCP server started in the outer process;
- any code execution chosen by the workload.

### 1.2 What was inferred from reading upstream source

The source was read at tag `v1.60.1` (commit `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd`, the
pinned commit) through `raw.githubusercontent.com`. Paths are under `openhands-agent-server/openhands/agent_server/`
unless they name `openhands-sdk/`; line numbers are at that tag.

1. **The resume loop.** `conversation_service.py` `ConversationService.__aenter__` (2238-2283)
   loads the catalog and calls `_get_or_load_event_service` for every record whose
   `base_state.json` `execution_status` is `RUNNING`. Errors are logged as
   `error_recovering_running_conversation` (2272-2276, which matches O1's journal line). The code
   comment calls this "crash recovery semantics … A live lease still prevents takeover". No
   condition looks at the conversation's runtime.
2. **The catalog.** `_load_catalog_sync` (594-641) reads every `<conversations_path>/<dir>/meta.json`
   (pydantic) and `base_state.json` (stdlib `json`) and keys the record by the stored `meta.json` id.
3. **Before the lease.** `_get_or_load_event_service_locked` (1094-1133) calls
   `_prepare_persisted_runtime` (1013-1039) **before** `_start_event_service`. That function runs
   `importlib.import_module` on each stored `tool_module_qualnames` value, `register_client_tools`
   on the stored client tools, and `_register_agent_definitions` (the process-wide subagent
   registry) on the stored agent definitions.
4. **The event service start.** `event_service.py` `EventService.start` (1239-):
   - claims the lease (1247-1254; `lease_ttl_seconds=0` disables leasing);
   - then creates the stored `workspace.working_dir` (`mkdir(parents=True, exist_ok=True)`,
     1258-1259) and runs `git init` there if it is not a repository (1260; 1212-1237);
   - constructs a `LocalConversation` in the server process (1353-);
   - rewrites `RUNNING` to `ERROR`, with a recovery event for an unmatched action (1424-).

   `openhands-sdk/.../conversation/impl/local_conversation.py` also creates the working
   directory (418-420). `openhands-sdk/.../conversation/state.py` logs
   `Resumed conversation %s from persistent storage` (602). Hooks, plugins, MCP servers and
   file-based agents are loaded lazily on first use (`_ensure_plugins_loaded`,
   `_ensure_agent_ready`), not in the constructor. Inference: the start path does not run them.
5. **Docker mode leaves the lease free.** In `api.py` (398-402), `conversation_registry.start()`
   runs before `async with service:`, with the comment "Runtime cleanup must precede
   external-catalog recovery so stale runtime owners cannot lose their expired leases to the outer
   service". `docker_runtime/registry.py` `DockerConversationRegistry.start` →
   `cleanup_stale_containers` (295-317) removes every owner-labelled container. No container's
   inner server is therefore alive to hold the lease, and the outer claim succeeds. The outer
   service's centralized loop then keeps renewing that lease (`_renew_all_leases_loop`), which
   explains O5. That explanation is an inference.
6. **The container writes its own record by design.** `docker_runtime/registry.py`
   `_build_container` (607-) bind-mounts the conversation's own directory read-write at
   `/var/openhands/conversations/<hex>` (668-672) and runs the container with
   `--user <server uid>:<server gid>` (694-695). The inner server must persist its own state, so
   the record the outer server reads at start is written from inside the container.
7. **The outer server can tell Docker-backed records apart but does not.**
   `docker_runtime/hybrid.py` `is_docker` (36-37) checks for the server-owned provisioning
   manifest (`runtime-control/<hex>.json`, outside every container mount). The resume loop does
   not consult it.
8. **Upstream's stated design for Docker mode.** Merged PR #5128 says the outer serves event
   history "without hydrating a workspace or acquiring a runtime lease". It also says historical
   local entries in a Docker-mode catalog report `can_resume=false`. Hydrating a Docker-backed
   record in the outer process at start appears inconsistent with that design.
9. **No switch.** `config.py` at the tag has no setting that disables or confines start-up
   recovery. `lease_ttl_seconds=0` only disables leasing.

**Newer releases** (read 2026-11-10):
- `v1.60.2` (`22a765e238aa8681277e392d00fdc950a230fbd8`): `conversation_service.py`,
  `event_service.py`, `api.py` and `docker_runtime/registry.py` are byte-identical to `v1.60.1`.
- `v1.61.0` (`a2ffb6ec21a6216edc9fc4b4739c076847f87e04`, released 2026-11-09, the latest release)
  and `main` at `79844cebdce44ac4b27dcd2929436cb6c363174a` (2026-11-10T00:23:30Z): the files
  differ, but `__aenter__`, `_prepare_persisted_runtime`, `_get_or_load_event_service_locked`,
  `_load_catalog_sync` and `EventService.start` are identical (an AST extraction of each, compared
  as text). The api.py ordering comment is unchanged.

**The path is unchanged in every current release.**

### 1.3 What is our deployment's choice, and what is not

**Ours:**
- running the outer server in Docker runtime mode, as a dedicated systemd service user in group
  `docker`, under `ProtectSystem=strict` with one writable home (decision 0001, F-04.1);
- the guest having no git;
- the drill helper's direct writes (O1, O2);
- the quiesce step (O7).

**Upstream's defaults, unchanged by us:**
- the read-write bind of the conversation directory and `--user` = the server's uid:gid (1.2
  item 6; recorded as our open risk `fd-container-shares-service-uid`, because we accept it);
- the shared catalog;
- the resume loop.

**Correction to the dispatch's premise.** The workload can write the record because of upstream's
own container design (the inner server persists its state), not because of a configuration of
ours. The report therefore does not present the writability as a defect. It treats it as a given
of the design and asks whether the outer server should act on that record.

### 1.4 Framing chosen, and why

The crash recovery itself is intended: the code comment says so, and it is reasonable for host-local
conversations. So the report does not call the resume a bug in general, and a "please stop resuming
`running` conversations" framing would be wrong.

What the evidence supports is narrower. **In Docker runtime mode, the outer server's start-up
recovery treats a Docker-backed conversation as host-local.** It runs the following in the outer
process, before or without any runtime-specific check:
- it imports module names stored in the container-written record;
- it registers that record's client tools and agent definitions;
- it creates and `git init`s that record's `working_dir` on the host (normally a container path);
- it takes and keeps the conversation's lease.

This appears to contradict upstream's own Docker-mode design (#5128). No setting disables or
confines it.

So the report is framed as a question with a concrete defect candidate:
1. Is this intended for Docker-backed conversations?
2. If not, can recovery for those records be confined to the status repair (no import, no
   registration, no host directory, no `LocalConversation`, no outer lease), or skipped?
3. Can start-up recovery be disabled by configuration?

The security relevance is stated as a trust-boundary question, without a claimed exploit.

The STOP condition (documented and intended, with a supported switch) does not hold: there is no
switch, and the Docker-mode behaviour conflicts with upstream's stated design.

The inventory's suggested fix, "hydrate only after a lease check", would not help in Docker mode.
The cleanup leaves the lease free (1.2 item 5), so the report does not propose it.

### 1.5 A defect found in our own record (not fixed here)

`security/inventory.json` `fd-outer-server-local-recovery` says the server imports, registers,
"creates the stored workspace.working_dir and runs git init there, before any lease check". At
`v1.60.1`:
- the import and registrations do precede the lease claim;
- the directory creation and `git init` come **after** it (`EventService.start` 1247-1260).

The claim succeeds in Docker mode because the cleanup has removed the containers. Classification:
introduced-by `e17ac2b` (the E-01.2.2c evidence commit that wrote the text). Not fixed here, because
this task may modify only this file. It is reported to the Overseer.

## 2. Sources reviewed

- **Repository** (read-only):
  - `evidence/E-01.2.2b-live-drills.md` s4.1-4.6, s8 (F-2, F-7);
  - `evidence/E-01.2.2c-fix-requalification.md` header, s4.1-4.3, findings (F-2, F-11);
  - `security/inventory.json` `fd-container-shares-service-uid` and `fd-outer-server-local-recovery`;
  - `decisions/0001-agent-server-dispatch-precondition-and-version-line.md` (the 1.60.1 line);
  - `composition/candidates.json` (`openhands-sdk`, `openhands-agent-server`);
  - `evidence/E-01.4.3-start-race.md` s9, s13 (the house style of OA-01 and OA-02).
- **Upstream source**, read unauthenticated through `raw.githubusercontent.com` at `v1.60.1`.
  `openhands-agent-server/openhands/agent_server/`:
  - `conversation_service.py`, `event_service.py`, `api.py`, `config.py`, `models.py`,
    `conversation_lease.py`;
  - `docker_runtime/registry.py`, `docker_runtime/hybrid.py`, `docker_runtime/provisioning.py`.

  `openhands-sdk/openhands/sdk/`: `conversation/impl/local_conversation.py`,
  `conversation/state.py`, `tool/registry.py`.

  The four agent-server files at `v1.60.2`, `v1.61.0` and `main@79844ce` were compared as in
  1.2. Tags were resolved through `api.github.com/repos/.../git/ref/tags/<tag>`, and releases
  were listed through `.../releases`.
- **The upstream security policy page** (`github.com/OpenHands/software-agent-sdk/security/policy`):
  it shows no published policy, with a "Report a vulnerability" entry. It was not opened while
  signed in, so whether private reporting is enabled for the Owner was not verified.

## 3. Duplicate check

GitHub's public issue search was used, unauthenticated, on 2026-11-10, over issues and PRs.

**Queries** (repository `OpenHands/software-agent-sdk` unless stated otherwise):
- `error_recovering_running_conversation`: 0 results;
- `tool_module_qualnames`;
- `crash recovery running conversation`;
- `resume running conversations startup`;
- `docker runtime working_dir host`;
- `external-catalog recovery`;
- `_prepare_persisted_runtime`;
- `owner_lease docker`: 0 results;
- `base_state.json running restart`;
- `docker runtime outer server running conversation`;
- `import_module meta.json`: 0 results;
- `container writable conversation store meta.json`;
- `docker-backed conversation recovery`;
- `stale running docker conversation startup`;
- `docker runtime isolation untrusted conversation state`;
- `resumed conversation workspace directory created`;
- `outer server lease docker inner 404`;
- `OpenHands/OpenHands`: `agent-server resume running conversation docker`;
- `OpenHands/OpenHands`: `tool_module_qualnames`.

**Closest matches. None is equivalent.**

| Item | State | Relation |
|---|---|---|
| #4893 "conversation stuck in execution_status=RUNNING after sandbox is paused/stopped mid-run" | open | The same recovery code, the opposite symptom: a local conversation that is *not* recovered (lease not expired). It does not concern Docker-backed records, outer-process hydration, imports or host paths. |
| #4897 "fix(agent-server): recover conversations after PID reuse" | open PR (fixes #4893) | It changes lease liveness, not what recovery does or for which runtime. It would not change this behaviour. |
| #5128 "fix(agent-server): preserve legacy conversations in Docker catalogs" | merged | Design context: in Docker mode, history is read "without hydrating a workspace or acquiring a runtime lease", and legacy local entries are `can_resume=false`. It does not touch start-up recovery. Cited in the draft. |
| #3403 "feat(agent-server): add docker runtime mode for per-conversation containers" | merged | It introduced the shared catalog ("synchronize the inner conversation catalog"). It does not discuss start-up recovery. |
| #5626 (pause not saved; after SIGKILL `error`), #5627 (`/goal` loop stays `running` after restart) | open | They concern status persistence across restarts in local mode, not Docker-backed recovery. |
| #5653 "Agent Server bugs found by the verify-agent-server feature map (umbrella)" | open | No matching item. It states that security-relevant findings are handled separately. |
| #5940 / #5958 (a tool module the server cannot import, rejected at create) | closed / merged | They validate `tool_module_qualnames` at create. They do not apply to a record changed afterwards. |
| #5067 / #5069 (restore tool registrations on remote attach) | closed / merged | They explain why `tool_module_qualnames` exists. They are unrelated to start-up recovery. |
| `OpenHands/OpenHands` #18715 (header says Running when the runtime is missing) | open | UI status only. |

**Outcome: no equivalent exists.** A new report is warranted; there is no URL to record instead.

## 4. The draft

> **Title:** Docker runtime: start-up crash recovery hydrates Docker-backed `running`
> conversations in the outer agent-server process (imports stored tool modules, creates the
> stored `working_dir` on the host, keeps the lease)
>
> **Versions**
> - openhands-agent-server **1.60.1** (tag `v1.60.1`, `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd`),
>   Linux x86_64 release binary, sha256
>   `b2fbcf8cf1495bdbef97f26583917bc188b765c71c181effc3e47c14da08ce72`.
> - Conversation image `ghcr.io/openhands/agent-server:1.60.1-python`, index digest
>   `sha256:b43ee580c2177280c81cb807c9a559d7a14aa13b48dba5040132a6a637bb6d55`.
> - Server configuration: `conversation_runtime=docker`, `conversation_runtime_selectable=false`,
>   `secret_key` set; the outer server runs as a dedicated non-root user in group `docker`.
> - The code path below is unchanged at v1.60.2 and v1.61.0, and on `main` at `79844ce`.
>
> **What happens**
>
> At start, `ConversationService.__aenter__` recovers every catalog record whose
> `base_state.json` says `running`. It does this through `_get_or_load_event_service`, whatever
> the conversation's runtime. For a **Docker-backed** conversation, in the **outer** process:
>
> 1. `DockerConversationRegistry.start()` first removes all of this server's conversation
>    containers (`cleanup_stale_containers`), so no inner server holds the conversation's lease.
> 2. `_prepare_persisted_runtime` imports every module named in the stored
>    `tool_module_qualnames`, and registers the stored client tools and agent definitions. This
>    happens before any lease claim.
> 3. `EventService.start` claims the lease, then creates the stored `workspace.working_dir` on
>    the host (`mkdir(parents=True)`) and runs `git init` there. For a Docker-backed record that
>    path is normally the container path `/workspace`.
> 4. A `LocalConversation` is built in the outer process, and the status is set to `error`.
>    The outer process then keeps renewing the lease.
>
> The record is written from inside the conversation container. `_build_container` bind-mounts
> the conversation's directory read-write and runs the container as the server's uid:gid, which
> the inner server needs in order to persist its state. A workload in the container can
> therefore set `execution_status`, `workspace.working_dir` and `tool_module_qualnames` in its
> own record, and they take effect in the outer process at its next start.
>
> **What we observed** (the release binary above, on a Debian 13 VM, no LLM configured)
> - A stored `running` record with its normal `working_dir`: at the next start the server
>   logged `error_recovering_running_conversation` (`conversation_service.py:2272`) and wrote a
>   state event. The outer view then reported the conversation `running`. In our deployment the
>   host `/workspace` is read-only to the service.
> - `running` with `meta.json` `workspace.working_dir` set to a new host path: at the next start
>   the server logged `Resumed conversation <id> from persistent storage` and
>   `Failed to initialize git repository at <path>` (git is not installed). It **created
>   `<path>`** (owned by the server's uid, mode 700), wrote `owner_lease.json` with its own
>   owner id and set the status to `error`. On one occasion the outer lease stayed in place and the
>   conversation's own inner server then answered 404 for it.
> - A process inside the conversation container (the container's uid) wrote `running` into its
>   record. That value survived a normal runtime stop (`DELETE /api/conversations/{id}/runtime`),
>   and the outer server ran the recovery path at its next start. When the container was killed
>   (`docker kill -s KILL`), a container-written `working_dir` also persisted.
> - The created container (image, mounts, caps, user, keys) was never affected.
>
> We did **not** observe:
> - the import step: we never set `tool_module_qualnames` together with `running`; the
>   description above is from the source;
> - a recovery of a conversation that was genuinely mid-run.
>
> **Minimal reproduction (not run in this form)**
>
> Linux host with Docker; the agent-server configured as above; the outer server running as a
> user who can write `/tmp`.
>
> 1. Start the server. Create a conversation with `"conversation_runtime": "docker"` (any agent
>    spec; no message and no LLM call needed). Note its id `<id>` (hex `<hex>`).
> 2. Stop its runtime (`DELETE /api/conversations/<id>/runtime`) and stop the server.
> 3. As the server's user (or from inside the container, through
>    `/var/openhands/conversations/<hex>/`), edit `<conversations_path>/<hex>/`:
>    - `base_state.json`: `"execution_status": "running"`;
>    - `meta.json`: `workspace.working_dir` → `/tmp/oh-resume-probe` (absent);
>    - `meta.json`: `"tool_module_qualnames": {"probe_tool": "oh_resume_probe_missing_module"}`.
> 4. Start the server.
>
> **Observed** (steps 1-4 as we ran them, without the `tool_module_qualnames` edit), and
> **expected from the source**:
> - a warning `Failed to import module 'oh_resume_probe_missing_module' for tool 'probe_tool'
>   when resuming <id>` (the import attempt; expected from the source, not observed by us);
> - `Resumed conversation <id> from persistent storage`;
> - `/tmp/oh-resume-probe` exists, owned by the server's user, with a `.git` if git is installed;
> - `owner_lease.json` names the outer server;
> - `base_state.json` is `error`.
>
> Leaving `working_dir` as stored gives the variant without tampering: the server tries to
> create `/workspace` on the host.
>
> **Expected**
>
> For a conversation that has a Docker provisioning manifest, start-up recovery should not
> hydrate it in the outer process. At most it should repair the stored status: no module
> import, no client tool or agent-definition registration, no host directory or `git init`, no
> `LocalConversation`, and no outer lease that the conversation's own runtime then cannot take.
> That matches the Docker-mode design in #5128 (history is served "without hydrating a
> workspace or acquiring a runtime lease").
>
> **Questions**
>
> 1. Is the outer-process recovery of Docker-backed conversations intended?
> 2. If not, could `__aenter__` skip records for which `is_docker()` (the provisioning manifest)
>    is true? Or could it confine them to the status repair, leaving any recovery event to the
>    inner server when the runtime is next provisioned?
> 3. Independently, could start-up recovery be disabled or restricted by configuration? Today
>    there is no setting for it (`lease_ttl_seconds=0` only disables leasing).
>
> **Security relevance**
>
> The conversation container is the isolation boundary for the agent's workload, and the outer
> server is the more privileged process: it holds the Docker engine and the per-conversation
> keys. With this path, values written by the workload into its own record become actions of
> the outer process at its next start:
> - creating a directory at a path of the workload's choosing, anywhere the server's user can
>   write, and running `git init` there;
> - importing a module named by the workload from among those importable by the server;
> - registering the workload's agent definitions and client tools in process-wide registries;
> - holding the conversation's lease.
>
> We have not shown code execution. We did not find a container-writable directory on the
> server's import path, but we did not inspect the frozen binary's `sys.path`. As far as we can
> tell from the source, hooks, plugins and MCP servers are loaded lazily and are not started by
> this path. Even so, a container-written record deciding imports and host paths in the outer
> process looks like an unintended crossing of that boundary.
>
> **Our mitigation**
>
> A root one-shot step runs before every server start. It removes all conversation containers
> and rewrites stored `running` to `error`; it also moves aside records that are links or that
> claim another conversation's id. With it, none of the effects above occurred in our drills.
> We would retire it once a release confines recovery for Docker-backed conversations.
