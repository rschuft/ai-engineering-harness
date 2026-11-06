# 0001 - Agent Server dispatch precondition and OpenHands version line

Status: Accepted (Overseer, under the Owner's adaptation directive) - 2026-11-06
Gate: architecture consultation, gates A (undermined premise) and G (containment)
Supersedes: none. Corrects the reading of blueprint #dispatch-contract and
#dispatch-probe-qualification. (Current fact, 2026-11-06: the blueprint was reconciled with this
record at M-1, commit e1ed236, through the authority-class manifest update; the original
import remains verifiable with `tools/verify_seed.py --baseline seed`.)

## Context
The blueprint gates native Docker dispatch on a pinned Agent Server that
"advertises selectable_conversation_runtime_v1", qualified at source against
v1.58.2 with three containment findings (caller-selectable host working_dir
bind-mount; uncapped per-conversation CPU/memory overrides; host-gateway
networking without --network none) and live qualification open. Upstream
server_details_router.py advertises no such token at v1.58.2, v1.59.0 or v1.60.1.
Selectability is the server configuration conversation_runtime_selectable,
surfaced as ServerInfo.available_conversation_runtimes (["local","docker"] when
set, [] by default); conversation_runtime_routes_v1 and
idempotent_conversation_create_v1 are advertised at all three versions. Agent
Canvas 1.36.0 requires Agent Server >= 1.59.0 and no Canvas release pinned 1.58.2.
The Agent Server's default per-conversation image is the floating tag
ghcr.io/openhands/agent-server:latest-python.

## Decision
1. F-01.2 locks the 1.60.1 line: openhands-sdk/-tools/-workspace/-agent-server
   1.60.1 (e99e5c7), @openhands/typescript-client 1.60.1, Agent Canvas 1.36.0
   (d30f1e4), openhands-automation 1.30.1 as a coupled pin, with the identifiers
   in composition/candidates.json. Revisit rule: re-resolve on an upstream pin
   change before F-04.1; on a version-attributable live failure fall back to the
   1.59.0 / Canvas 1.35.0 set, never to 1.58.2.
2. The dispatch precondition is restated as observed GET /server_info
   conditions: ("docker" in available_conversation_runtimes or
   conversation_runtime == "docker") and "conversation_runtime_routes_v1" in
   capabilities; the retry rule additionally requires
   "idempotent_conversation_create_v1". Every create sends
   conversation_runtime:"docker" explicitly with the reserved conversation_id;
   any non-2xx is a refusal; the effective runtime is verified by independent
   docker inspect before an attempt counts as contained. Required server
   configuration: conversation_runtime=docker, conversation_runtime_selectable
   =false by default (hybrid mode only by recorded exception), OH_SECRET_KEY set,
   conversation_image set to the locked digest. Docker-only is the default
   configuration, not a rule; making it a rule would be a separate, Proposed
   decision.
3. The v1.58.2 containment findings hold at 1.60.1 (cited docker_runtime files
   identical or unchanged in the launch-flag region) and are re-examination
   obligations carried by E-01.2.2, S-01.3.1, F-04.2, S-02.1/S-02.2 (working_dir);
   E-01.2.2, F-04.1, F-03.2.1 (resource caps); F-03.3.2, S-01.4, S-01.3.2, S-02.1
   (network). No leaf is added or weakened.
4. The lock carries conversation_image =
   ghcr.io/openhands/agent-server@sha256:b43ee580c2177280c81cb807c9a559d7a14aa13b48dba5040132a6a637bb6d55
   as a locked artifact; the latest-python default is non-conforming. F-04.1
   enforces it in server configuration; F-04.2 and E-01.5 observe it.

## Consequences
- Intent of the blueprint precondition is preserved; its observable changes from
  a version capability to configuration plus observation, so F-04.1 owns the
  configuration and E-01.3.1/E-01.5 own the runtime check. The blueprint's token
  is a documentation defect exposed by F-01.1, corrected in the blueprint at M-1 (e1ed236).
- E-01's and F-01's acceptance criteria are unchanged.
- Open: a public per-conversation runtime discriminator was not established at
  1.60.1; E-01.3.1/E-01.5 validate against the pinned OpenAPI.
- Migrate this record into OpenSpec when adopted.

## Clarification (2026-11-06, Owner direction; no change to the decision)
`conversation_runtime=docker` names the Agent Server's Docker-API runtime path, and
"docker-only" is an implementation safety setting for the current execution path. It
does not architecturally exclude Podman's Docker-compatible API (an ADAPT/QUALIFY
alternative per blueprint #infrastructure-state), the dedicated-VM LocalWorkspace
profile, or other approved providers. Any material change to isolation guarantees,
provider choices, or authority boundaries still requires architectural evaluation.
The blueprint passages this record corrects will be reconciled with it at maintenance
item M-1, after F-02 makes the blueprint's integrity metadata updatable through a
versioned process.

## Evidence
composition/compatibility-matrix.md s2.1, s4, s5, s6; composition/candidates.json;
blueprint #dispatch-contract, #dispatch-probe-qualification, #infrastructure-state,
#decisions, #components. Upstream at tags (raw.githubusercontent.com/OpenHands/
software-agent-sdk/<tag>/openhands-agent-server/openhands/agent_server/):
server_details_router.py (v1.58.2, v1.59.0, v1.60.1); config.py 87, 404-433;
conversation_registry.py 84-95; conversation_router.py 336-340;
docker_runtime/routers.py 138-139; docker_runtime/registry.py 674-720;
docker_runtime/provisioning.py 146-158; openhands-sdk/openhands/sdk/conversation/
request.py 480-486; diff of hybrid.py, provisioning.py, conversation_router.py,
registry.py, routers.py, config.py between v1.58.2 and v1.60.1. Canvas
config/defaults.json at v1.34.0, v1.35.0, v1.36.0. PyPI openhands-automation
1.26.1 requires_dist. GitHub releases v1.59.0, v1.60.0, v1.60.1.
