# The Agent Server fixture's cited core (E-01.4.2, slice 5c; the container inspect, E-01.5) and the served fixture (E-01.7, slice 9)

The one fixture catalog, the core that answers from it, and, since E-01.7, the listener that serves it with two faces
([below](#the-served-fixture-e-017)). The core answers in process (the dispatch suites, the restart matrix) and,
through `server.py`, on the host loopback. Since E-01.8 the composition root `run.py` dispatches a ready task through
the production path on it ([below](#the-composition-e-018)).

- `observations.json`: the catalog. Each answer is an entry; each field of each entry has its provenance class, its
  citation, the inputs that determine it, whether the dispatch path reads it, whether it is served, and its marks.
- `core.py`: `AgentServerCore`, which answers a dispatcher request by its route **and the conversation's state**, from
  the catalog only. A request outside the catalog, or one whose answer would need a field of no class, is refused with
  the fixture's label. It records every request it receives in its call log (what the fake received), and, under a
  read recorder, every key read of its answers with its reader, failing closed on any other read of an answer (its
  module docstring names exactly which operations are recorded). Standard library only.
- The provenance table below. A test binds it to `observations.json` row for row, and the read-binding test binds its
  **Read** column, and the functions it names, to what the dispatch path reads.

**Authority:** plan leaf E-01.4.2's proof as amended on 2026-11-16 (I1 recovery), and E-01.7's proof, which carries
the same rules for the same catalog; planning's disposition of PB-10 to PB-12
([bootstrap log](../../evidence/bootstrap-log.md#i1-recovery-disposed-2026-11-16)); the
[restart-recovery design](../../evidence/I1-restart-recovery-design-2026-11-16.md) sections 4.4 and 4.5; decision 0026
(Proposed); the engineering manager's readings below.

## The provenance classes

E-01.7's four classes, and nothing else:

| Class | What it is |
|---|---|
| `observation` | A recorded observation, cited to the committed record of the live run that observed it (F-04.2's lifecycle; where F-04.2 did not observe it, F-04.1c, the E-01.3.x or S-01.3.1 evidence, or the D1 run record of 2026-11-16), served only when the inputs that determine it equal the observed request's. A **clock-valued** field reproduces its cited value unchanged, whatever the request's time, and is marked `clock-valued`. |
| `echo` | A value echoed from the request. |
| `pinned-rule` | A value derived by a rule pinned in an accepted decision, or in harness code outside the fixture that the production path itself runs, named. |
| `label` | The fixture's label. |

A field of none of those classes is **not served**: it is listed with its answer as "not served", and the answer
carries no value for it. A request whose answer the dispatch path would read from such a field is refused with the
fixture's label. The one exception is the **source-derived** entry below (the fields the dispatch path reads of the
event that records the dispatcher's own initial message): derived from the pinned upstream source, marked
`source-derived`, not observed, answered in process only.

## The records cited

| Key | Record |
|---|---|
| F-04.2 §4.1 to §4.9 | [evidence/F-04.2-conversation-lifecycle.md](../../evidence/F-04.2-conversation-lifecycle.md), section 4 (run A, `f042-a`): 4.1 the fixture and the routes, 4.2 create, 4.3 inspect (the server's view and the root facts: the container's docker inspect), 4.4 the persisted events, 4.6 stop, 4.9 delete |
| F-04.2 §1, §7 | the same record: section 1, the pinned server's container build (`registry.py`: `--add-host host.docker.internal:host-gateway`, no `--network`); section 7, the containment deviations as observed on every container of run A |
| F-04.1c §3 | [evidence/F-04.1c-agent-server.md](../../evidence/F-04.1c-agent-server.md), section 3 (run 1, `f041c-a`): `/server_info` as returned (complete), and `/api/conversations/count` (body `0`) |
| D1 §5 | [evidence/D1-run-2026-11-16.md](../../evidence/D1-run-2026-11-16.md), section 5: the steps (2), (3), (4), (5b), (6), (7b), (9), (10) and "The dispatcher's calls" (method, path, status of every call) |
| D1 §4 | the same record, section 4 ("Before the dispatch"): the profile's sha256, the provision lock and the image the guest was provisioned with |

Every observation in this catalog is cited to one of these. None needed the E-01.3.x or S-01.3.1 evidence: S-01.3.1's
refused create is E-01.7's failed scenario (slice 9), not an answer E-01.4.2 uses.

## The pinned upstream source (the source-derived entry, and the determining inputs it identifies)

Read as data only (not installed, imported or run), from the locked wheels, each checked against the lock before it
was read:

| Wheel | sha256 | Lock |
|---|---|---|
| `openhands_sdk-1.60.1-py3-none-any.whl` | `f6efa8f8428ccc8abebbcf4c424bf3008a66a46f9f2340d37b3b306fcb45eb6b` | `composition/lock/components.lock.json` (`openhands-sdk`) |
| `openhands_agent_server-1.60.1-py3-none-any.whl` | `df80a622059f3cce797ab2c08adfc5256a69d7c7a6b4712b2d5147df25be76f6` | `composition/lock/components.lock.json` (`openhands-agent-server`) |

Citations below are `sdk:<in-wheel path>:<line>` for the first and `as:<in-wheel path>:<line>` for the second.

- **How the dispatcher's message is recorded.** `POST /api/conversations/{id}/events` reaches the inner server's
  event write route through the outer server's proxy (`as:openhands/agent_server/docker_runtime/routers.py:361`),
  which builds `Message(role=request.role, content=request.content)` and calls `send_message(message, request.run)`
  (`as:openhands/agent_server/event_router.py:226-227`). The event service hands the message to the conversation
  before it consults the run flag (`as:openhands/agent_server/event_service.py:906-907`), and the conversation
  records `MessageEvent(source="user", llm_message=message, ...)` (`sdk:openhands/sdk/conversation/impl/local_conversation.py:2041-2043`).
  `MessageEvent` has `source: SourceType` and `llm_message: Message` (`sdk:openhands/sdk/event/llm_convertible/message.py:32-35`);
  `Message` has `role` and `content: Sequence[TextContent | ImageContent]` (`sdk:openhands/sdk/llm/message.py:222-226`);
  `TextContent` has `type: "text"` and `text: str` (`sdk:openhands/sdk/llm/message.py:177-179`).
- **How an event is read back.** The outer server mounts the persisted event read routes itself
  (`as:openhands/agent_server/docker_runtime/registry.py:210-215`). `GET .../events/search` answers
  `{"items": [<each event's model_dump(mode="json", exclude_none=True)>], "next_page_id": ...}`
  (`as:openhands/agent_server/event_router.py:129-138`).
- **The page's determining inputs.** The search's `limit` defaults to `100` (`gt=0, le=100`;
  `as:openhands/agent_server/event_router.py:76-79`), so a request with no query has F-04.2's `?limit=100`; and
  `next_page_id` is set only when more events match than the limit (`as:openhands/agent_server/event_service.py:689-690`),
  otherwise it stays `None` (`:680`). These identify the determining inputs of the cited `next_page_id`; they are
  not its value.
- **What determines the create's status** (the `create-new` `status` row). The outer server answers with the status
  of its conversation container (`as:openhands/agent_server/docker_runtime/routers.py:221`), which is `201` for a
  conversation it did not hold (`as:openhands/agent_server/conversation_router.py:360`). The matrix's create differs
  from D1's (D1 §5 (2), `201`) only by the `acp_model` value (`syn-model-a` for `claude-sonnet-5`) and the secret
  values (the same four names); neither determines the status. `acp_model` is a plain `str | None` with no validator
  (`sdk:openhands/sdk/settings/model.py:1866`), at the create only the agent's model label
  (`sdk:openhands/sdk/agent/acp_agent.py:2005-2009`). A plaintext `StaticSecret` value is any non-empty string, kept
  as a `SecretStr` (`sdk:openhands/sdk/secret/secrets.py:96`, `:103-106`;
  `sdk:openhands/sdk/utils/pydantic_secrets.py:124-158`), decrypted only for `secrets_encrypted`, which the
  dispatcher's create sends `false` (`as:openhands/agent_server/docker_runtime/routers.py:239`,
  `as:openhands/agent_server/launch.py:182-186`). Neither value reaches the provider at the create: the agent is
  initialized only at its first run (`sdk:openhands/sdk/conversation/impl/local_conversation.py:357`, `:2104-2107`),
  an ACP agent not even on a message (`:1761-1769`), and an ACP server's refusal of the model is tolerated then
  (`sdk:openhands/sdk/agent/acp_agent.py:857-886`). The core checks only the `conversation_id` (a UUID it does not
  hold): **it does not validate the rest of a create's body** in this slice. Validation against the locked OpenAPI
  document or the pinned response model is E-01.7's (slice 9, the fixture's listener).
- **`/server_info` and the profile's configuration** (the `server-info` rows). The served fields that depend on the
  server's configuration are named in `build_server_info` and its route
  (`as:openhands/agent_server/server_details_router.py:159-192`): `conversation_runtime` (`:170`),
  `available_conversation_runtimes` (`:171-173`), `app_backend_ingress_url` (`:174`), `usable_tools` (`:175`) and
  `capabilities` (one more only with an ingress URL, `:177-180`). Only `usable_tools` depends on the browser
  (`browser_available`, `:147-156`, `:191`). The profile's server configuration changed, from the commit F-04.1c ran
  (`90816fa`) to the profile D1 ran (`9684d9c`, sha256 `b7c5d2fe…`), only by `enable_browser: false` (881e728), and
  the browser is unavailable on both sides of it: before it, by the image, a tag not the stock repository's with
  `conversation_image_has_browser` unset (F-04.1c §2, "Configuration as written";
  `as:openhands/agent_server/launch.py:109-122`, `:128-134`; `as:openhands/agent_server/config.py:87`); from it, by
  `enable_browser` false (`as:openhands/agent_server/launch.py:118-119`). So F-04.1c's `usable_tools` is the value
  over the whole range `90816fa..9684d9c`, the range each configuration-determined row names. Two unread fields
  cannot be shown equal over it, and are not served (dispatch 14, follow-up): `runtime_idle_timeout_seconds` and
  `max_foreground_terminal_timeout_seconds` take no configuration argument but come from openhands-tools
  (`:15-18`, `:62-64`, `:98-100`), which is not among the extracted wheels, and the profile's server environment
  gained `LITELLM_LOCAL_MODEL_COST_MAP` at 574d8db, within the range.
- **A conversation never created** (the `conversation-absent` `status` row). `GET /api/conversations/{id}` answers
  404 when the outer server's conversation service has neither a record nor an event service for the id
  (`as:openhands/agent_server/conversation_router.py:229-231`,
  `as:openhands/agent_server/conversation_service.py:1136-1143`). A delete leaves exactly that (its manifest and
  directory removed, then the record dropped: `as:openhands/agent_server/docker_runtime/routers.py:336-342`,
  `as:openhands/agent_server/conversation_service.py:984-989`), and so does an id never created: F-04.2 §4.9's 404
  after the delete is the answer for both.
- **The empty log before the message** (the `events` `body.items` row). F-04.2 §4.4's `[]` is a plain `Agent`'s
  log after its create. No event is recorded before the agent is initialized, for either agent kind
  (`sdk:openhands/sdk/conversation/impl/local_conversation.py:357`, `:549-550`); an ACP agent is not initialized on
  a message either (`:1761-1769`). SEED's command events are files of their own, `<conversation dir>/bash_events`
  (`as:openhands/agent_server/dependencies.py:99-105`), apart from the conversation's event log
  (`sdk:openhands/sdk/conversation/persistence_const.py:5`). So the log of D1's ACP-agent conversation after SEED
  and before its message is that same empty page.

## The provenance table

One row per field. **Read**: the dispatch path reads it, and where: each function of `integrations/dispatch/` that
reads it, `<module>.<function>` (both bound by the read-binding test, which records the innermost dispatch function
under each read). **Served**: the core puts a value in the answer. Paths: `status`, `body.<key>`, `[]` for each
element of a list; `fixture` is the label. The configuration range `90816fa..9684d9c` is defined
[above](#the-pinned-upstream-source-the-source-derived-entry-and-the-determining-inputs-it-identifies).

| Answer | Field | Class | Citation | Determined by | Read | Served | Marks |
|---|---|---|---|---|---|---|---|
| `server-info` | `status` | observation | F-04.1c §3; F-04.2 §4.1; D1 §5 calls | the route (no input) | yes: `dispatch_inputs.server_preconditions` | yes | |
| `server-info` | `body.version` | observation | F-04.1c §3; F-04.2 §4.1 | the server's build | yes: `dispatch_inputs.server_preconditions` | yes | |
| `server-info` | `body.capabilities` | observation | F-04.1c §3 (F-04.2 §4.1 names two of them) | the server's build, and the profile's server configuration (`app_backend_public_url`, unset over 90816fa..9684d9c: `as:openhands/agent_server/server_details_router.py:177-180`, `:189`) | yes: `dispatch_inputs.server_preconditions` | yes | |
| `server-info` | `body.conversation_runtime` | observation | F-04.1c §3; F-04.2 §4.1 | the profile's server configuration (`conversation_runtime`, unchanged over 90816fa..9684d9c: `as:openhands/agent_server/server_details_router.py:170`, `:187-188`) | yes: `dispatch_inputs.server_preconditions` | yes | |
| `server-info` | `body.available_conversation_runtimes` | observation | F-04.1c §3; F-04.2 §4.1 | the profile's server configuration (`conversation_runtime_selectable`, unchanged over 90816fa..9684d9c: `as:openhands/agent_server/server_details_router.py:171-173`, `:190`) | yes: `dispatch_inputs.server_preconditions` | yes | |
| `server-info` | `body.uptime` | observation | F-04.1c §3 | the clock | no | yes | clock-valued |
| `server-info` | `body.idle_time` | observation | F-04.1c §3 | the clock | no | yes | clock-valued |
| `server-info` | `body.app_backend_ingress_url` | observation | F-04.1c §3 | the profile's server configuration (`app_backend_public_url`, unset over 90816fa..9684d9c: `as:openhands/agent_server/server_details_router.py:174`, `:189`) | no | yes | |
| `server-info` | `body.build_git_ref` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.build_git_sha` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.docs` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.max_foreground_terminal_timeout_seconds` | none | not served: its value comes from openhands-tools (`as:openhands/agent_server/server_details_router.py:15-18`, `:98-100`), which is not among the extracted wheels, and the profile's environment changed since the observation (`LITELLM_LOCAL_MODEL_COST_MAP`, 574d8db, within 90816fa..9684d9c), so its determining inputs cannot be shown equal; not read | | no | no | |
| `server-info` | `body.python_version` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.redoc` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.runtime_idle_timeout_seconds` | none | not served: its value comes from openhands-tools (`as:openhands/agent_server/server_details_router.py:15-18`, `:62-64`), which is not among the extracted wheels, and the profile's environment changed since the observation (`LITELLM_LOCAL_MODEL_COST_MAP`, 574d8db, within 90816fa..9684d9c), so its determining inputs cannot be shown equal; not read | | no | no | |
| `server-info` | `body.sdk_version` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.title` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.tools_version` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.usable_tools` | observation | F-04.1c §3 | the server's build, and the profile's server configuration (the browser: unavailable over 90816fa..9684d9c, before 881e728 by the image, from it by `enable_browser: false`; `as:openhands/agent_server/server_details_router.py:147-156`, `:175`, `:191`, `as:openhands/agent_server/launch.py:109-122`, `:128-134`) | no | yes | |
| `server-info` | `body.workspace_version` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `fixture` | label | the fixture's label | | no | yes | |
| `create-new` | `status` | observation | F-04.2 §4.2; D1 §5 (2); the `acp_model` value and the secret values, in which the matrix's create differs from D1's, do not determine it (the README's upstream source: `as:openhands/agent_server/docker_runtime/routers.py:221`, `as:openhands/agent_server/conversation_router.py:360`, `sdk:openhands/sdk/settings/model.py:1866`, `sdk:openhands/sdk/utils/pydantic_secrets.py:124-158`, `sdk:openhands/sdk/conversation/impl/local_conversation.py:1761-1769`) | a `conversation_id` that is a UUID the server does not hold | yes: `dispatch_inputs.create_receipt` | yes | |
| `create-new` | `body.id` | echo | the request's `conversation_id` | the request | yes: `dispatch_inputs.create_receipt` | yes | |
| `create-new` | `body.created_at` | observation | F-04.2 §4.2 | the clock | no | yes | clock-valued |
| `create-new` | `body.execution_status` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.tags` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.title` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.workspace` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.agent` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.confirmation_policy` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.stats` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.metrics` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.secret_registry` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.runtime_info` | observation | F-04.2 §4.2 | the request other than `conversation_id` (F-04.2's fixture request) | no | yes | equal request only |
| `create-new` | `body.persistence_dir` | observation | F-04.2 §4.2 | the whole request, `conversation_id` included (F-04.2's own request) | no | yes | equal request only |
| `create-new` | `body.<the other top-level fields of the 36>` | none | not served: no committed observation (F-04.2 §4.2 records selected fields; the full answer is not committed) | | no | no | |
| `create-new` | `fixture` | label | the fixture's label | | no | yes | |
| `conversation` | `status` | observation | F-04.2 §4.3; D1 §5 (3), (6) | a conversation the server holds | yes: `attempt_end._answer`, `attempt_end.prior_runtime`, `reconcile._lookup`, `reconcile.verdict_of`, `restart_recovery._lookup_reserved` | yes | |
| `conversation` | `body.id` | echo | the request path's `conversation_id` | the request | yes: `attempt_end.observe`, `attempt_end.prior_runtime`, `attempt_run.inspect_conversation`, `reconcile.verdict_of` | yes | |
| `conversation` | `body.execution_status` | observation | `idle`: F-04.2 §4.3 (a created conversation, no message); `finished`: D1 §5 (6) (its turn ended) | the conversation's state; `finished` by the fixture's transition on the message (no turn runs) | yes: `attempt_end._finished`, `attempt_end.observe`, `attempt_run.conversation_status` | yes | scenario: the core's transition (by call count) |
| `conversation` | `body.<every other ConversationInfo field>` | none | not served: no committed observation of its value | | no | no | |
| `conversation` | `fixture` | label | the fixture's label | | no | yes | |
| `conversation-absent` | `status` | observation | F-04.2 §4.9 (`GET` after the delete: 404); a conversation never created answers alike, neither having a record or an event service (`as:openhands/agent_server/conversation_router.py:229-231`, `as:openhands/agent_server/conversation_service.py:1136-1143`; the delete leaves none: `as:openhands/agent_server/docker_runtime/routers.py:336-342`, `as:openhands/agent_server/conversation_service.py:984-989`) | a conversation the server does not hold | yes: `attempt_end.prior_runtime`, `reconcile._lookup`, `reconcile.verdict_of`, `restart_recovery._lookup_reserved` | yes | |
| `conversation-absent` | `body.detail` | none | not served: F-04.2 §4.9 records the status only | | no | no | |
| `conversation-absent` | `fixture` | label | the fixture's label | | no | yes | |
| `count` | `status` | observation | F-04.1c §3; D1 §5 (3), (10) | the route (no input) | yes: `attempt_run._plain` | yes | |
| `count` | `body` | observation | `0`: F-04.1c §3, D1 §5 (10); `1`: D1 §5 (3) | the number of conversations the server holds (0 or 1; any other number is refused) | yes: `attempt_run._plain` | yes | |
| `count` | `fixture` | label | the fixture's label | | no | yes | |
| `runtime` | `status` | observation | F-04.2 §4.3, §4.6; D1 §5 (3), (9) | a conversation the server holds | yes: `attempt_end._answer` | yes | |
| `runtime` | `body.runtime_status` | observation | `available`: F-04.2 §4.3, D1 §5 (3) (after the create); `missing`: F-04.2 §4.6, D1 §5 (9) (after the runtime stop) | the conversation's state | yes: `attempt_end.runtime_status` | yes | |
| `runtime` | `body.can_resume` | observation | F-04.2 §4.3, §4.6; D1 §5 (3) | the conversation's state (`true` in both) | no | yes | |
| `runtime` | `fixture` | label | the fixture's label | | no | yes | |
| `runtime-stop` | `status` | observation | F-04.2 §4.6; D1 §5 calls (`DELETE .../runtime` 204) | a held conversation whose runtime is `available` | yes: `attempt_end._answer` | yes | |
| `runtime-stop` | `body` | pinned-rule | the observed `204` (F-04.2 §4.6; D1 §5 calls), by the production path's rule for an answer with no content: `tools/guest.py:9128` (`API_PROBE`: `json.loads(text) if text else None`), `integrations/dispatch/guest_transport.py:192` (`response.get('body')`) | the status (`204`: no content) | yes: `attempt_end._answer` | yes | |
| `runtime-stop` | `fixture` | label | the fixture's label | | no | yes | |
| `seed` | `status` | observation | D1 §5 calls (`POST .../bash/execute_bash_command` 200, SEED) and (4) | the harness's SEED command, the first on a held conversation, and its exit `0` (another exit is refused with the label: no record observes it) | yes: `attempt_run.run_attempt` | yes | |
| `seed` | `body.stdout` | pinned-rule | `integrations/dispatch/attempt_run.py` `SEED_SCRIPT`, run over the request's payload (its success line `AIEH-SEED ok <sha256> <files>`) | the request's payload and digest | yes: `attempt_run.run_attempt` | yes | |
| `seed` | `body.exit_code` | pinned-rule | `integrations/dispatch/attempt_run.py` `SEED_SCRIPT`, run over the request's payload | the request's payload and digest (served only as `0`) | yes: `attempt_run.run_attempt` | yes | |
| `seed` | `body.stderr` | none | not served: not observed, and not read | | no | no | |
| `seed` | `body.command_id`, `body.kind`, `body.id`, `body.timestamp`, `body.order` | none | not served: no committed observation of its value, and not read; `BashOutput` requires `command_id` and `kind` (`as:openhands/agent_server/models.py:669-687`), listed here (the dispatcher's-face clause) | | no | no | |
| `seed` | `fixture` | label | the fixture's label | | no | yes | |
| `message` | `status` | observation | D1 §5 calls (`POST .../events` 200, the message) | the message tail, the first on a held conversation | yes: `attempt_run.send_message` | yes | |
| `message` | `body` | none | not served: not observed (D1's call list records the status only) | | no | no | |
| `message` | `fixture` | label | the fixture's label | | no | yes | |
| `events` | `status` | observation | F-04.2 §4.4 | a held conversation; no query | yes: `attempt_end._answer` | yes | |
| `events` | `body.items` | observation | F-04.2 §4.4 (`[]` on an empty log, a plain `Agent`'s create); an ACP agent's log is as empty before its message, SEED included: no event before the agent is initialized (`sdk:openhands/sdk/conversation/impl/local_conversation.py:357`), for an ACP agent not on the message (`:1761-1769`), and a command's events kept apart (`as:openhands/agent_server/dependencies.py:99-105`, `sdk:openhands/sdk/conversation/persistence_const.py:5`); on a non-empty log, the catalog's events (`message-event`) | the conversation's recorded events; a non-empty log by the fixture's transition on the message (its event recorded; no turn runs) | yes: `attempt_end.observe` | yes | scenario: the core's transition (by call count) |
| `events` | `body.next_page_id` | observation | F-04.2 §4.4 (`null`) | no `page_id`, and the log within one page at the effective limit (`as:openhands/agent_server/event_router.py:76-79`, `as:openhands/agent_server/event_service.py:689-690`) | yes: `attempt_end.observe` | yes | engineering manager's reading |
| `events` | `fixture` | label | the fixture's label | | no | yes | |
| `message-event` | `kind` | observation | D1 §5 (7b) (`MessageEvent` in the log of a conversation that received the dispatcher's message) | the event's type | yes: `attempt_run.message_received` | yes | |
| `message-event` | `source` | source-derived | `sdk:openhands/sdk/conversation/impl/local_conversation.py:2041-2043`; `sdk:openhands/sdk/event/llm_convertible/message.py:32` | a user message sent to the conversation | yes: `attempt_run.message_received` | yes | source-derived |
| `message-event` | `llm_message` | source-derived | `sdk:openhands/sdk/event/llm_convertible/message.py:33-35`; `as:openhands/agent_server/event_router.py:226` | the message | yes: `attempt_run._message_texts` | yes | source-derived |
| `message-event` | `llm_message.content` | source-derived | `sdk:openhands/sdk/llm/message.py:226`; `as:openhands/agent_server/event_router.py:226` | the request's `content` | yes: `attempt_run._message_texts` | yes | source-derived |
| `message-event` | `llm_message.content[].text` | echo | the request's `content[].text` (`sdk:openhands/sdk/llm/message.py:179`) | the request | yes: `attempt_run._message_texts` | yes | source-derived |
| `message-event` | `id`, `timestamp`, `llm_message.role`, `llm_message.content[].type`, `llm_response_id`, `activated_skills`, `extended_content`, `sender`, `critic_result` | none | not served: no committed observation, and not read | | no | no | |
| `container-inspect` | `body.Image` | observation | F-04.2 §4.3 (`.Image`, the locked image ID); D1 §5 (3) (one container, of the conversation, no container problem) | the image the guest's Agent Server was provisioned with: the profile's provision lock `f02e430a…` at F-04.2's run (`fec83d9`) and at D1's (`9684d9c`; D1 §4, the provision: image `sha256:e8959dfc…`) | yes: `launch_gate._plain` | yes | |
| `container-inspect` | `body.HostConfig.Memory`, `body.HostConfig.NanoCpus`, `body.HostConfig.PidsLimit` | observation | F-04.2 §4.3 (`Memory` 4294967296, `NanoCpus` 2000000000, `PidsLimit` 512, "= config"); D1 §5 (5b) (`cpu.max` 200000 100000, `memory.max` 4294967296, `pids.max` 512; "the same caps in `HostConfig`") | the profile's server configuration (`conversation_container_memory` `4g`, `conversation_container_cpus` 2.0, `conversation_container_pids_limit` 512, the same at `fec83d9` and `9684d9c`) and a create that sends no `container.memory` or `container.cpus` (F-04.2 §7, the request caps override; both pinned templates send `container` `{"browser": false}` only) | yes: `launch_gate._plain` | yes | |
| `container-inspect` | `body.HostConfig.NetworkMode` | observation | F-04.2 §4.3 (network `bridge`), §7 (`HostConfig.NetworkMode` `bridge`) | the server's build: the pinned server passes no `--network` (F-04.2 §1, §7: `registry.py`), the same server and image at D1 | yes: `launch_gate._plain` | yes | |
| `container-inspect` | `body.HostConfig.ExtraHosts` | observation | F-04.2 §4.3 (`ExtraHosts` `host.docker.internal:host-gateway`), §7 (`["host.docker.internal:host-gateway"]`) | the server's build: `--add-host host.docker.internal:host-gateway`, unconditional (F-04.2 §1, §7: `registry.py` line 704), the same server and image at D1 | yes: `launch_gate._plain` | yes | |
| `container-inspect` | `body.Mounts[].Type`, `body.Mounts[].RW` | observation | F-04.2 §4.3 (`Mounts` exactly the three declared binds, `RW` true); D1 §5 (3) (workspace scope exactly the three declared binds) | the profile's declared mounts (`provisioning.agent_server.conversations.mounts`: three, each `bind` and `rw` true, the same at `fec83d9` and `9684d9c`) | yes: `launch_gate._plain` | yes | |
| `container-inspect` | `body.Mounts[].Source`, `body.Mounts[].Destination` | pinned-rule | the declared mounts of the profile D1 ran (`profiles/strong-windows-qemu-whpx/profile.json`, sha256 `b7c5d2fe…`, `provisioning.agent_server.conversations.mounts`) expanded with the conversation's hex by `integrations/dispatch/dispatch_inputs.py` `_binds_for`, the admission's own rule; F-04.2 §4.3 and D1 §5 (3) observed exactly the declared binds | the request's conversation id (its hex) | yes: `launch_gate._plain` | yes | |
| `container-inspect` | `body.<every other field of the container's inspect>` | none | not served: not read by the gate, which compares the fields above only (F-04.2 §4.3 records others, the container's name, labels, user, options and ports among them, and the mounts' `Mode` and `Propagation`; the guest's own inspection compares them: `tools/guest.py` `container_problems`) | | no | no | |
| `container-inspect` | `fixture` | label | the fixture's label | | no | yes | |
| `refusal` | `status` | label | the fixture's refusal: `501` | | no | yes | |
| `refusal` | `fixture` | label | the fixture's label, with the reason it refused | | no | yes | |

**Not served**, by answer: `server-info`, `runtime_idle_timeout_seconds` and `max_foreground_terminal_timeout_seconds`
(the catalog keeps F-04.1c's whole block as `recorded`; `body`, the served answer, is that block less exactly these
two); `create-new`, every top-level field but those listed served (and, for a request that is not
F-04.2's fixture request, every field but `id` and `created_at`); `conversation`, every field but `id` and
`execution_status`; `conversation-absent`, its body; `seed`, `stderr`, and `BashOutput`'s required `command_id` and
`kind` with `id`, `timestamp` and `order` (listed by E-01.7's G4); `message`, its body; `message-event`, every
field but `kind`, `source`, `llm_message.content[].text` and the two containers that hold it.

**The source-derived entry:** one, `message-event` (the event that records the dispatcher's own initial message). Its
source-derived fields are `source` and the content that holds the message text (`llm_message`, `llm_message.content`,
and the text's place in it); its `kind` is observed and its text is the request's echo. Answered in process only; the
answer's label names the source-derived fields. Its observed counterpart is E-01.6's: E-01.6 compares each with the
event its own initial message records, read live (that message differs from the dispatcher's only by the run flag,
and the event is recorded before the flag is consulted: `as:openhands/agent_server/event_service.py:906-907`), corrects
the catalog where they diverge and re-runs E-01.4.2's restart matrix. E-01.6's live run also observes the non-empty
events page.

## The engineering manager's readings, 2026-11-16

Recorded as delegated decisions on dispatch 12 of unit I1:

1. **The events page on a non-empty log** (engineering manager's reading, 2026-11-16). No committed record observes a
   non-empty events page (searched: the D1 run record, the E-01.3.x evidence, S-03.3-D-1, F-04.1c; E-05.8 records
   the paging as unverified live). So `next_page_id` `null` is cited to F-04.2 §4.4, with its determining inputs "no
   `page_id`, and the log's size within one page at the effective limit"; the pinned source establishes the default
   limit and that rule, as the identification of the determining inputs, not as the value. `items` holds the
   catalog's events: on a non-empty log, the source-derived entry's read fields, each other field of it by its own
   class. E-01.6's live run observes the non-empty page.
2. **The SEED success line** (engineering manager's reading, 2026-11-16): class `pinned-rule`, by running the
   harness's own `attempt_run.SEED_SCRIPT` over the request's payload in a scratch directory (no visible window). The
   200 is cited to D1's call list. A second SEED on one conversation has no observation and is refused with the label.
   So is a SEED whose script exits other than `0` (dispatch 14, ruling N1): no record observes a 200 with such an
   exit.
3. **RESULT** (engineering manager's reading, 2026-11-16): no observation covers this catalog's RESULT, so it is
   refused with the label; in the restart matrix's rows J, K and L the row's "then" is that `resume_result` reaches
   exactly one RESULT, refused, and the row's verdict rests on the create and message counts and the turn state.
4. **Classes** (engineering manager's reading, 2026-11-16): as in the table. `running` is not served; the restart
   matrix's row L dies at the wait's first read, a listed transport event (the request never arrives).
5. **Knobs** (engineering manager's reading, 2026-11-16): every behaviour of the existing fakes outside the catalog
   stays in its test module as a subclass or wrapper (below). `CountingTransport` (`test_dispatch_admission.py`) is
   not one of the three fakes and is out of scope.

Dispatch 14 of unit I1 (the engineering manager's rulings on the review of slice 5c):

- **The `runtime-stop` answer's `body`** (S1): class `pinned-rule`, built on the observed `204`. A `204` carries no
  content, and the production path's own rule makes that `null`: the guest's API probe, `tools/guest.py:9128`
  (`API_PROBE`: `json.loads(text) if text else None`), and the live transport,
  `integrations/dispatch/guest_transport.py:192` (`response.get('body')`). `attempt_end._answer` reads it and
  `stop_runtime` discards it.
- **The core's own scenario** (S4): two transitions are the fixture's, not a run's, and their rows are marked
  "scenario: the core's transition (by call count)": the conversation's `finished` and the events page's non-empty
  `items`, both on the message, with **no turn run**. The cited values stay the observations (D1 §5 (6), the
  `message-event` entry); what the row's "determined by" adds is that this request leads to them in the fixture.

## The core's behaviour by state

The core holds, per conversation: whether it exists, its execution status (`idle` after its create, `finished` once
its message is received), its runtime status (`available` after the create, `missing` after the runtime stop),
whether it was seeded, and its events (the `message-event` once the message is received). Its scenarios advance by
the requests it receives (by call count), never by a clock. It has no clock, no route that reaches a guest, a model
or a credential, and no listener. **No turn runs**: on the message the core records the message's event and goes
`finished` at once, the fixture's own transition (the scenario mark in the table); a live run would run the agent's
turn between the two, and record its events too (E-01.6 observes it).

| Request | Condition | Answer |
|---|---|---|
| `GET /server_info` | always | `server-info` |
| `POST /api/conversations` | a `conversation_id` that is a UUID it does not hold (the rest of the body unchecked) | `create-new` (the conversation now held) |
| `GET /api/conversations/count` | 0 or 1 held | `count` |
| `GET /api/conversations/{id}` | held / not held | `conversation` / `conversation-absent` |
| `GET .../runtime` | held | `runtime` |
| `DELETE .../runtime` | held, runtime `available` | `runtime-stop` (runtime now `missing`) |
| `POST .../bash/execute_bash_command` | the harness's SEED command, the conversation held and not yet seeded, the script's exit `0` | `seed` (another exit: `refusal`) |
| `POST .../bash/execute_bash_command` | the harness's RESULT command, after SEED and the finished turn, over D1's base and recorded changes (`result.py`; E-01.7) | `result` (else `refusal`) |
| `POST .../events` | the message tail, the conversation held, no message yet | `message` (the `message-event` recorded; status `finished`; no turn runs) |
| `GET .../events/search` | held, no query | `events` |
| (not a route) `container_inspect(id)` | held, runtime `available` | `container-inspect` (else `refusal`) |
| anything else | | `refusal` |

## The call log, transport events and test knobs

- **The call log** (`AgentServerCore.calls`) records what the fake received: each request the core was called with,
  in order. A request that a transport event drops before the core leaves no entry.
- **Transport events** are not catalog answers. A test injects them outside the core, as a wrapper: a request that
  never arrives (the core is not called), a response withheld (the core answered; the caller gets an exception), and a
  dispatcher's death (a `BaseException`) with either. The restart matrix lists them with its rows
  ([integrations/dispatch/README.md](../dispatch/README.md#the-restart-matrix-e-0142-slice-5c)).
- **Test knobs** are answers no cited run gave. They live in the test modules, as subclasses or wrappers of the core,
  unreachable from it, and decide no row of the restart matrix:
  - `test_conversation_create.FakeAgentServer` (E-01.3.1): `info`, `info_error`, `create`, `create_error`, and the
    `persistence_dir` it derives from the request's id;
  - `test_attempt_end.ConversationServer` (E-05.8): the initial status `running`, the 404's `detail`, the event
    search's pages of `PAGE` events, `set` (status, events, runtime), `fail`, and the runtime stop answered `204`
    whatever the runtime's state;
  - `test_attempt_run.RunServer` (D1 slice A2): `count`, the message's answers (`message_status`, `after_message`),
    SEED and RESULT run for real by bash over a temporary workspace (`real`) or SEED's canned success line, and the
    lost or failed answers (`lose_results`, `fail_stops`).

## The container inspect (E-01.5)

E-01.5's launch gate (`integrations/dispatch/launch_gate.py`) compares an independent docker inspect of the attempt's
container with the admitted values. Offline, that inspect is the catalog's `container-inspect` entry, answered by
`AgentServerCore.container_inspect(conversation id)`, the recorded inspect source of the I1 design's R13. It is **not
an Agent Server route**: the live source is the guest's root facts (`tools/guest.py`, F-04.2 section 2, "The on-demand
facts"), and no request path reaches it here. The answer has no HTTP status (`body` and the label only); each inspect is
noted in `inspected` with the length of the call log at that moment, and not in `calls`.

- **When it answers.** A container exists exactly while the conversation is held with its runtime `available`: after
  the create (F-04.2 §4.3; D1 §5 (3)), and no longer after the runtime stop (F-04.2 §4.6: "no owned container"). A
  conversation not held, or whose runtime is `missing`, is refused with the label.
- **What it serves** (the provenance table, answer `container-inspect`): exactly the five fields the gate compares, as
  docker inspect names them. `Image`, the caps (`HostConfig.Memory`, `NanoCpus`, `PidsLimit`), `HostConfig.NetworkMode`
  and `HostConfig.ExtraHosts` are F-04.2 §4.3's and §7's values, corroborated by D1 §5 (3) and (5b). The mounts are the
  declared binds of the profile D1 ran, checked by its sha256 (`b7c5d2fe…`, D1 §4), expanded with the conversation's
  hex by the admission's own rule (`dispatch_inputs._binds_for`), under the field names the guest's own check reads
  (`tools/guest.py` `effective_container_mounts`: `Type`, `Source`, `Destination`, `RW`). F-04.2 §4.3 and D1 §5 (3)
  observed exactly those binds. Every other field of a container's inspect is not served.
- **The equivalent-request rule.** Each served value is determined by inputs that are the same at F-04.2's run
  (`fec83d9`) and at D1's (`9684d9c`): the provision lock `f02e430a…` (the image), the server's configured caps with a
  create that sends no container caps (both pinned templates send `container` `{"browser": false}` only), the server's
  build (1.60.1, the same image: `NetworkMode` and `ExtraHosts`), and the declared mounts. `test_agentfixture_core`'s
  `ContainerInspect` checks each value in its cited section and each determining input in the checked-in records.
- **Altered copies** (one per compared field) and an inspect that cannot be obtained are test knobs in
  `integrations/dispatch/tests/test_launch_gate.py` (`Altered`, and sources that raise or answer no inspect object):
  answers no cited run gave, made outside the core.

## The served fixture (E-01.7)

`server.py` serves this catalog on one host-loopback listener, `127.0.0.1:13320` (`server.PORT`; a test binds a free
port of its own), Starlette on uvicorn under the tools interpreter (the I1 design's R1 and R12; decision 0026,
Proposed). `transport.py` is the dispatcher's fixture transport to it. `result.py` builds RESULT's answer. The
listener and the edge to it are recorded in `policy/network-matrix.json` (`nm-dispatcher-agentfixture`) and
`security/inventory.json` (`api-agentfixture`) before it first listens.

**Authority:** plan leaf E-01.7's proof as amended on 2026-11-16 (I1 blockers and I1 recovery); the I1 design's R8 to
R13 and slice 9; the engineering manager's rulings of dispatch 24 (below).

### Two faces, one port

| | The dispatcher's face | The UI face |
|---|---|---|
| Path | the root | under `/ui` (the prefix is removed before the route is matched) |
| Who calls it | the dispatcher, through `transport.py` | the Owner UI and Agent Canvas only (Canvas through upstream's static server: U-01.2, slice 13); the dispatcher never does |
| Access value | `agentfixture-dispatcher-face-public-value` in `X-Session-API-Key` | `agentfixture-ui-face-public-value`, in `X-Session-API-Key` or the session socket's first frame |
| The other face's value | refused: `unauthorized` (S-01.3.1's `401 {"detail": "Unauthorized"}`; E-01.3.3 step (4) observed the runtime credential refused by the outer server) | refused: `ui-unauthorized` |
| Public | `GET /server_info`, as the pinned server's | `GET /server_info` |
| Writes | the dispatcher's own: the create, SEED and RESULT, the message, the runtime stop | none: every method but `GET` is refused with the label, before the key is checked, and so is every inbound message on the session socket but an authentication frame (the pinned socket would run it: G10) |
| Answers | the core's entries above, and `result` and `unauthorized` below | the `ui-` entries below |
| Source-derived | at most one entry, `message-event`, answered in process only: **the listener refuses the request that would need it** (an event search whose answer would hold it) | only for a field the committed evidence does not observe, only in the statuses idle, running and finished; named in the answer's label (`sourceDerived`) |
| Read by the dispatch path | the rows marked read | nothing |

**The label** is on every HTTP answer and on the session socket's handshake: the header `X-AIEH-Fixture`, the
catalog's label as JSON with the answer's name (and, on the UI face, `face` and `sourceDerived`). Where the schema
has room the UI face also shows it in the data (`title`, `tags`). `transport.py` refuses an answer without it
(`FIXTURE_LABEL_MISSING`).

**Refusals.** A request outside the catalog, or one whose answer would need a field no class admits (other than a
property listed not served on the dispatcher's face), is answered HTTP 501 with the label (`FIXTURE_NO_OBSERVATION`
and why). A body that cannot be parsed, or that parses but is nested deeper than 64 levels (the core copies and
walks bodies recursively), is the labelled 400 (`malformed`) before the core sees it, never an unlabelled error. A refused socket is closed 1008 with the reason
`FIXTURE_NO_OBSERVATION: <why>` after a labelled handshake. A request line the HTTP layer itself rejects (uvicorn's
own 400, before the application runs) carries no label: no application code sees it.

**CORS** (the engineering manager's ruling 2 of E-01.7's review). The dispatcher's face has none: no browser drives
it, so a preflight there is the labelled 501 and no answer carries an `Access-Control-*` header. The UI face answers a
browser only from origins configured explicitly (`--ui-origin`; none by default; loopback `http` origins only,
`localhost` or `127.0.0.1`, the origins the pinned CORS middleware allows (`as:openhands/agent_server/middleware.py:52-60`;
`[::1]` is not one), another refused at start with `UI_ORIGIN_NOT_LOOPBACK`), only for `GET` of a route its
catalog serves, asking for no header but `X-Session-API-Key`, and never with credentials: the preflight is the
labelled `ui-preflight` (its status source-derived from the pinned server's own preflight through Starlette's
`CORSMiddleware`, `as:openhands/agent_server/middleware.py:34-50`), with `Access-Control-Allow-Origin` (that origin),
`-Methods` `GET` and `-Headers` `x-session-api-key`; any other preflight is the labelled 501. Those headers are the
listener's own policy, as its label header is, not fields of an answer. A preflight is matched to the UI `GET` route
it precedes (a reading: the pinned server's CORS middleware answers a preflight before any route; the inventory lists
no preflight route). Agent Canvas needs none of this: it reaches the UI face through upstream's static server, whose
reverse proxy makes its requests same-origin (the I1 design's R14 fact 2), so no credentials mode is needed.

**Create validation** (the engineering manager's ruling 2, carried from E-01.4.2). Before the core sees a create, its
body is validated against the locked release document's `StartConversationRequest` with the harness's
standard-library schema subset (`tools/check_profile.py` `schema_errors`). The document is `openapi.json` of release
v1.60.1, sha256 `3de49fac…e0d0` (`composition/lock/components.lock.json`): never committed (decision 0005); the
process is given its path (`--openapi`) and checks its sha256. A body that does not validate, or any create while no
document is given, is refused with the label and never answered 201.

**What it never does.** It opens no outbound connection: once its event loop exists, an audit hook refuses every
`socket.connect` and `socket.getaddrinfo` in the process (the Integration process's measured pattern). The process
shows it armed itself: before its ready line it tries one connect to its own listener (`guard_probe`, the served
sources' one connect call site) and records in `<state-dir>/guard.json` that the guard refused it. Its core calls run
off the event loop, one at a time (a worker thread under one lock): SEED and RESULT run a process, and meanwhile the
loop goes on answering what needs no core state. It imports no
client module (`transport.py` is the client; the server never loads it, nor any dispatch module: the core reads the
SEED and RESULT scripts from `attempt_run.py`'s source as data). No route reaches a guest, a model or a credential;
it never executes what it receives (the core runs only the harness's own SEED and RESULT scripts, recognized byte for
byte, over pinned inputs). The call log (`--log`, a file outside the checkout, JSON lines) records each request's face,
method, path, the catalog answer or the transport event, never a body: it is the evidence of "exactly one create and
one initial message".

### Scenarios

Chosen when the process starts (`--scenario`); each advances by call count, never by a clock or a control route. A
transport event is not an answer: the listener holds the request and sends nothing until the client goes away.

| Scenario | What the clients see | Transport events |
|---|---|---|
| `finished` | the dispatcher's face as the core answers it; the UI face idle until the message, then finished | none |
| `running` | as `finished` on the dispatcher's face; the UI face shows the conversation running for 7 of its own conversation reads after the message (D1's wait read the conversation seven times: D1 §5 calls), then finished | none |
| `pending` | the conversation stays idle: the dispatcher's message never reaches the core. Over the listener the attempt run ends `TURN_UNRECONCILED`, its turn journal `unknown` (`no-answer`), its conversation idle with no message; `recover` sends nothing again | the first `POST .../events`: the request never reaches the core; its response is withheld |
| `failed` | S-01.3.1's observed refusal of a create: the dispatcher's face admits no key, so the create (and every key-gated request) is answered `unauthorized` | none |
| `lost-create-acknowledgement` | the create is received and its acknowledgement lost (the dispatch leaves the attempt `unknown`, `create-unanswered`); E-01.4.1's reconcile finds the conversation and confirms the attempt on it; no second create | the first `POST /api/conversations`: it reaches the core; its response is withheld |
| `unknown` | the create is received and its acknowledgement lost, and so is every lookup of that conversation: E-01.4.1's reconcile leaves the attempt `unknown` (`still_unknown`), and E-01.4.2's `recover` asks once more and holds it (`OUTCOME_UNKNOWN`, its lookup `indeterminate`); no second create | the first `POST /api/conversations`, and each `GET /api/conversations/{id}` of that conversation: each reaches the core; each response is withheld |

**The two faces can diverge in time** (the engineering manager's ruling 1 of dispatch 24, option (A)). No committed
record observes a non-terminal status read after the dispatcher's message (D1's seven wait reads are recorded without
their values, and F-04.2 sent no message), so the dispatcher's face never serves one: it answers `finished` at the
first read after the message, with the core's scenario mark. The UI face may serve `running`, source-derived, as the
proof admits there; in the running scenario it does so for its own call count. A UI view can therefore show a turn
running while the dispatcher has already taken it as finished. The "unknown" scenario is built from withheld answers
only (ruling 3): the listener never needs the source-derived `message-event`.

The outcomes in the table for `pending`, `lost-create-acknowledgement` and `unknown` are shown over the listener by the
production paths themselves (`tests/test_scenarios.py`: the dispatch, E-01.4.1's `reconcile_creates`, E-01.4.2's
`recover` and the attempt run, unmodified, through the fixture transport), a withheld answer ending at the transport's
injected ceiling; `failed`'s by the restart matrix over the listener (`test_read_binding.ServedReadBinding`).

**The session socket** sends, at connect, the one `sync` frame and the replay of the events above `after_seq`, and no
live frame after: an event recorded while a socket is open reaches the client at its next connect. U-01.2's gate G5
must account for it.

**Records.** Every answer carries the fixture's label, and an answer without it never reaches the dispatch path (the
transport refuses it); no answer can be taken as live (`lineage_resolve.answering_authority`: `test_served.Authority`).
The labels on the dispatcher's own records ("every record it causes", criterion 11) are E-01.8's (the I1 design's R11).

### RESULT (`result.py`)

The harness's own `RESULT_SCRIPT` (read from `attempt_run.py`'s source, compared byte for byte), run by the core over
D1's base and D1's recorded file changes (the engineering manager's ruling 4 of dispatch 24), answered only when every
input that determines its answer is pinned: the builder's constants; the conversation seeded and its turn finished;
the seeded workspace, outside `openspec/` and `backlog/`, D1's demo repository by blob id (planning's PB-7). D1's
three changes come from D1's Owner report, reproduced verbatim in the D1 run record and checked by its sha256
(`4c2e6826…c338`); they are applied to a copy of the seeded workspace, and the script runs over it in scratch, with no
visible window. Its output lines are the script's own (pinned rule), the commit by decision 0024 point 4.4's rule
(G7: equal to `attempt_run.expected_commit`'s object over the printed tree, and to the real script's output through a
real shell on the same inputs). The identity is an input: the script takes the name, email, date and message the
command carries. The test output served is D1's recorded one (114 bytes, sha256 `432e7641…7754`), cited only for that
fixed command over D1's base and changes, and only when the script's own run of the tests passed; the duration that
run printed is not served. **The exchange delivery (`delivered`) is the transport's** (E-01.8; the I1 design's R13):
the listener serves no delivery; `transport.py`, given an exchange directory, applies `tools/guest.py`'s own
`API_PROBE` delivery rule to the labelled answer ([below](#the-composition-e-018)), and refuses a delivery without one.

### G4: the locked document, route by route

The locked release `openapi.json` (sha256 `3de49fac…e0d0`, equal to the lock's and to its release's `SHA256SUMS`
line, which equals the lock's `6b6e6e3f…37e9`) compared with the pinned route inventory
(`profiles/strong-windows-qemu-whpx/agent-server/routes.json`, sha256 `919d67e2…bc09`, of the profile D1 ran,
`b7c5d2fe…d9c7`), by method and path template, on 2026-11-16 (dispatch 24): the document has 140 paths and 169
operations, all under `/api/`; 148 of the inventory's 193 routes are in it (148 of the 170 sourced `openapi`, none of
the 4 `framework` and none of the 19 `binary`). Not in it: `GET /server_info` (and `/`, `/alive`, `/health`, `/ready`),
`DELETE .../runtime`, the conversation proxy `POST .../{tail}` and every WebSocket. It defines the inner server's
conversation-scoped routes (local runtime), among them `POST .../events` and `POST .../bash/execute_bash_command`,
which the inventory reaches through the proxy's closed `tails`. PB-1's premise holds. Every route the fixture serves
is in the inventory:

| Face | Method | Route (prefix removed) | Inventory route (source) | In the locked document | Answers | Validated against |
|---|---|---|---|---|---|---|
| dispatcher | GET | `/server_info` | `/server_info` (openapi) | no | `server-info`, `refusal` | model `ServerInfo` (`as:openhands/agent_server/server_details_router.py:38-103`), the schema below |
| dispatcher | POST | `/api/conversations` | `/api/conversations` (openapi) | yes | `create-new`, `unauthorized`, `refusal` | model `ConversationInfo` (`as:openhands/agent_server/models.py:357`), as the locked document carries its schema (`#/components/schemas/ConversationInfo`); the request against `#/components/schemas/StartConversationRequest` |
| dispatcher | GET | `/api/conversations/count` | `/api/conversations/count` (openapi) | yes | `count`, `unauthorized`, `refusal` | an integer (`as:openhands/agent_server/conversation_router.py:215-216`) |
| dispatcher | GET | `/api/conversations/{conversation_id}` | `/api/conversations/{conversation_id}` (openapi) | yes | `conversation`, `conversation-absent`, `unauthorized`, `refusal` | model `ConversationInfo` (`as:openhands/agent_server/models.py:357`), as the locked document carries its schema; 404 without a body schema |
| dispatcher | GET | `/api/conversations/{conversation_id}/runtime` | `/api/conversations/{conversation_id}/runtime` (openapi) | yes | `runtime`, `unauthorized`, `refusal` | model `ConversationRuntimeInfo` (`as:openhands/agent_server/models.py:67-72`) |
| dispatcher | DELETE | `/api/conversations/{conversation_id}/runtime` | `/api/conversations/{conversation_id}/runtime` (openapi) | no | `runtime-stop`, `unauthorized`, `refusal` | 204, no content (`as:openhands/agent_server/docker_runtime/routers.py:291-292`) |
| dispatcher | GET | `/api/conversations/{conversation_id}/events/search` | `/api/conversations/{conversation_id}/events/search` (openapi) | yes | `events`, `unauthorized`, `refusal` | model `EventPage` (`as:openhands/agent_server/models.py:461-463`; the locked document's response schema is empty) |
| dispatcher | POST | `/api/conversations/{conversation_id}/events` | `/api/conversations/{conversation_id}/{tail}` (openapi) | no | `message`, `unauthorized`, `refusal` | model `Success` (`as:openhands/agent_server/models.py:453-454`, the proxied local route's answer); the tail `events` of the inventory's closed `tails` |
| dispatcher | POST | `/api/conversations/{conversation_id}/bash/execute_bash_command` | `/api/conversations/{conversation_id}/{tail}` (openapi) | no | `seed`, `result`, `unauthorized`, `refusal` | model `BashOutput` (`as:openhands/agent_server/models.py:669-687`), as the locked document carries its schema; the tail `bash/execute_bash_command` of the inventory's closed `tails` |
| ui | GET | `/server_info` | `/server_info` (openapi) | no | `ui-server-info`, `refusal` | model `ServerInfo` (`as:openhands/agent_server/server_details_router.py:38-103`) |
| ui | GET | `/api/conversations/{conversation_id}` | `/api/conversations/{conversation_id}` (openapi) | yes | `ui-conversation`, `ui-unauthorized`, `refusal` | the locked document's `#/components/schemas/ConversationInfo` (the local runtime's route) |
| ui | GET | `/api/conversations/{conversation_id}/events/search` | `/api/conversations/{conversation_id}/events/search` (openapi) | yes | `ui-events`, `ui-unauthorized`, `refusal` | the locked document (an empty response schema) and model `EventPage` (`as:openhands/agent_server/models.py:461-463`), each item the locked `#/components/schemas/Event` |
| ui | GET | `/api/settings` | `/api/settings` (openapi) | yes | `ui-settings`, `ui-unauthorized`, `refusal` | the locked document's `#/components/schemas/SettingsResponse` (model `SettingsResponse`, `as:openhands/agent_server/settings_router.py:118-119`) |
| ui | WEBSOCKET | `/sockets/session/{conversation_id}` | `/sockets/session/{conversation_id}` (binary) | no | `ui-socket`, `ui-sync`, `ui-durable`, `ui-socket-unauthorized`, `ui-socket-denied`, `socket-refusal` | models `SyncFrame` and `DurableFrame` (`as:openhands/agent_server/session_protocol.py:51-81`), the schemas below |

**Validation** (the engineering manager's G4 readings of dispatch 24). The dispatcher's face (the outer, Docker-mode
server, for whose runtime the locked document defines no route) is validated against the pinned wheel's response
models, named per route above; where the locked document carries the same release's model as a schema
(`ConversationInfo`, `ConversationRuntimeInfo`, `BashOutput`, `Success`, `Event`), that schema is its JSON form, and
the others are written in the catalog (`served.schemas`) from the model's source. The UI face (a conversation's own
server, the local runtime) is validated against the locked document where it defines the route, and `events/search`
(an empty response schema there) against model `EventPage` as well. On the dispatcher's face a required property no
class admits and the dispatch path does not read is listed not served (the seed row above; `result` below); its
absence alone is not a validation failure. The validation that needs the locked document runs when its path is given
(`AIEH_LOCKED_OPENAPI`, sha256-checked); the catalog's own schemas are checked in every run.

### The dispatch suite against the served core, and the read binding over the listener

`integrations/dispatch/tests/read_binding_runner.py --served` runs a dispatch test module, unmodified, with every
request a test sends to a core (`AgentServerCore.__call__`) carried over HTTP to the listener serving that same core
(in a thread of the runner's process), through `transport.py`; the read record sits at the fixture transport's answer
boundary. A request no wire carries (a keyword argument: the exchange delivery) stays in process, where the core
refuses it as before. `test_read_binding.ServedReadBinding` (E-01.7's extension of the read-binding test) runs every
module so, the restart matrix again in the `failed` scenario, and RESULT's answer read by the production parser
(`attempt_run.parse_result`, as the resumed result step calls it), and requires:

- the only failing tests are the three restart-matrix rows that settle a turn from the event log (J, J' and K): the
  listener refuses the event search whose answer would hold the source-derived `message-event`, as the proof
  requires; every other test of the dispatch suite passes against the served core;
- the failed-scenario run fails on its refused creates (its return code, its failures, the 401 given to the dispatch
  path);
- every read is of a row marked read, served and not clock-valued (the judge of E-01.4.2's binding, over the core's
  rows and the served rows);
- RESULT's `body.stdout` is one text whose marker lines are rows of their own: a line row is read exactly when the
  production parser refuses the text without that line (each line taken away in turn; the table is not consulted);
- each served row marked read is read, by exactly the dispatch functions its Read column names.

One row is a transport key (its mark, the engineering manager's ruling 7 of E-01.7's review): RESULT's `delivered`,
which the production parser reads (absent) on the answer, a key the exchange delivery adds and not a field of the
Agent Server's answer, outside criterion 7's served fields. It is never served; the judge lists its read apart, by the
row's mark. The delivery is E-01.8's seam. The binding needs the locked document (the listener validates every
create), so it runs when `AIEH_LOCKED_OPENAPI` is given and is skipped otherwise, saying so.

## The served fixture's provenance table

The listener's additions to the catalog (`observations.json` `served`), one row per field, with the face that serves
it. A test binds this table to the catalog row for row. Paths as above; `close.*` is a socket's close frame;
`body.stdout#<line>` is one marker line of RESULT's output (`AIEH-RESULT <line> ...`; `frame` the exchange frame's
lines).

| Face | Answer | Field | Class | Citation | Determined by | Read | Served | Marks |
|---|---|---|---|---|---|---|---|---|
| dispatcher | `result` | `status` | observation | D1 §5 calls (`POST .../bash/execute_bash_command` 200 (RESULT, ...)) and (8) | the harness's RESULT command (its script byte for byte `RESULT_SCRIPT`, the builder's constants), after the core's SEED and the finished turn, on the seeded workspace, whose files outside `openspec/` and `backlog/` are D1's demo repository by blob id, with D1's recorded changes applied; the script's exit `0` | yes: `attempt_run.parse_result` | yes |  |
| dispatcher | `result` | `body.exit_code` | pinned-rule | `integrations/dispatch/attempt_run.py` `RESULT_SCRIPT` (run by the core over the seeded workspace with D1's changes; served only as `0`) | the harness's RESULT command (its script byte for byte `RESULT_SCRIPT`, the builder's constants), after the core's SEED and the finished turn, on the seeded workspace, whose files outside `openspec/` and `backlog/` are D1's demo repository by blob id, with D1's recorded changes applied; the script's exit `0` | yes: `attempt_run.parse_result` | yes |  |
| dispatcher | `result` | `body.stdout#base`, `body.stdout#tree`, `body.stdout#commit`, `body.stdout#excluded`, `body.stdout#bundle`, `body.stdout#done` | pinned-rule | `integrations/dispatch/attempt_run.py` `RESULT_SCRIPT`, its own output lines: the commit by decision 0024 point 4.4's rule (`attempt_run.expected_commit` over the printed tree, the base, the identity, the date and the message the command carries; G7), its bundle and the excluded paths; D1's commit id `51af29e4…` a citation only (D1 §2) | the command's parameters (base, bundle, identity, date, message) and the edited workspace | yes: `attempt_run.parse_result` | yes |  |
| dispatcher | `result` | `body.stdout#tests` | observation | D1 §5 (8) and §2 (Tests in RESULT: status `0`, `PASSED`) | D1's test command (`RESULT_SCRIPT`'s fixed `python -m unittest discover -s tests`) over D1's base outside `openspec/` and `backlog/` and D1's changes (planning's PB-7); served only when the script's own run of it passed | yes: `attempt_run.parse_result` | yes |  |
| dispatcher | `result` | `body.stdout#test-output` | observation | D1 §5 (8) and §2 (Tests in RESULT: output 114 bytes, sha256 `432e7641…7754`), the bytes as D1 §12's Owner report shows them (the report's sha256 `4c2e6826…c338` checked) | D1's test command over D1's base outside `openspec/` and `backlog/` and D1's changes (planning's PB-7); served only when the script's own run of it passed | yes: `attempt_run.parse_result` | yes |  |
| dispatcher | `result` | `body.stdout#frame` | pinned-rule | `integrations/dispatch/attempt_run.py` `RESULT_SCRIPT` (the frame it prints when the command asks for the exchange delivery) | the command's `frame` parameter | no | yes |  |
| dispatcher | `result` | `body.stderr`, `body.command_id`, `body.kind`, `body.id`, `body.timestamp`, `body.order` | none | not served: no committed observation of its value, and not read; `BashOutput` requires `command_id` and `kind` (`as:openhands/agent_server/models.py:669-687`), listed here (the dispatcher's-face clause) |  | no | no |  |
| dispatcher | `result` | `delivered` | none | not served: the transport's key, not a field of the Agent Server's answer (the exchange delivery, E-01.8's seam: the I1 design's R13; the engineering manager's ruling 7 of E-01.7's review: outside criterion 7's served fields); the production parser reads it, absent, at this answer's boundary until the seam adds it; over the listener the whole result path is proven at E-01.8 |  | yes: `attempt_run.parse_result` | no | transport key: E-01.8 |
| dispatcher | `result` | `fixture` | label | the fixture's label |  | no | yes |  |
| dispatcher | `unauthorized` | `status` | observation | S-01.3.1 §3.4 (`401 {"detail": "Unauthorized"}`, a key-gated HTTP route with no key or a wrong key); E-01.3.3 §8.3 step (4), PASS live at §9.1 (a key the outer server does not hold, the runtime credential, answered 401 on its key-gated routes) | a key-gated route (every route of the face but `GET /server_info`) with no key or a key not the face's; in the failed scenario every key | yes: `dispatch_inputs._dispatch`, `dispatch_inputs.create_receipt`, `reconcile._lookup`, `reconcile.verdict_of`, `restart_recovery._lookup_reserved` | yes |  |
| dispatcher | `unauthorized` | `body`, `body.detail` | observation | S-01.3.1 §3.4 (`{"detail": "Unauthorized"}`) | as `status` | yes: `dispatch_inputs.create_receipt`, `reconcile.verdict_of` | yes |  |
| dispatcher | `unauthorized` | `fixture` | label | the fixture's label |  | no | yes |  |
| ui | `ui-server-info` | `status` | source-derived | `as:openhands/agent_server/server_details_router.py:184-192` (the public route answers `ServerInfo`) | the route (no input) | no | yes | source-derived |
| ui | `ui-server-info` | `body.uptime`, `body.idle_time` | observation | F-04.1c §3 | the clock | no | yes | clock-valued |
| ui | `ui-server-info` | `body.<every other ServerInfo field>` | none | not served: unobserved at the UI's vantage and not required (`ServerInfo` requires `uptime` and `idle_time` only: `as:openhands/agent_server/server_details_router.py:38-103`) |  | no | no |  |
| ui | `ui-server-info` | `fixture` | label | the fixture's label, naming the source-derived fields |  | no | yes |  |
| ui | `ui-conversation` | `status` | source-derived | `as:openhands/agent_server/conversation_router.py:219-234` (`ConversationInfo` for a conversation the server holds) | a conversation the server holds, idle, running or finished | no | yes | source-derived |
| ui | `ui-conversation` | `body.id` | echo | the request path's `conversation_id` | the request | no | yes |  |
| ui | `ui-conversation` | `body.workspace` | source-derived | the conversation's state (`as:openhands/agent_server/conversation_service.py:387-388`, `sdk:openhands/sdk/conversation/state.py:95`): the create's `LocalWorkspace` and its `working_dir` | the conversation's create (its `workspace`) | no | yes | source-derived |
| ui | `ui-conversation` | `body.agent` | source-derived | the conversation's state (`sdk:openhands/sdk/conversation/state.py:86`): an ACP `agent_settings` create becomes an `ACPAgent` (`sdk:openhands/sdk/conversation/request.py:517-519`, `sdk:openhands/sdk/settings/model.py:2142-2160`) whose `acp_command` is the settings' own when not empty and not an `npx` command (`sdk:openhands/sdk/settings/model.py:2047-2073`); only `kind` and `acp_command` (the required pair) are served | the conversation's create (`agent_settings`: `agent_kind` `acp`, `acp_command`) | no | yes | source-derived |
| ui | `ui-conversation` | `body.execution_status` | source-derived | `sdk:openhands/sdk/conversation/state.py:125` (`idle`, `running`, `finished`) | the conversation's state: `idle` before the message; then `finished`, or in the running scenario `running` for that scenario's number of the UI face's own reads first | no | yes | source-derived; scenario: the UI face's call count |
| ui | `ui-conversation` | `body.title`, `body.tags` | label | the fixture's label (where the schema has room, in the data the UI shows: the I1 design's R12) |  | no | yes |  |
| ui | `ui-conversation` | `body.<every other ConversationInfo field>` | none | not served: unobserved at the UI's vantage and not required (`ConversationInfo` requires `id`, `workspace` and `agent`) |  | no | no |  |
| ui | `ui-conversation` | `fixture` | label | the fixture's label, naming the source-derived fields |  | no | yes |  |
| ui | `ui-events` | `status` | source-derived | `as:openhands/agent_server/event_router.py:68-71`, `:129-138` (`EventPage` for a conversation it holds) | a conversation the server holds, idle, running or finished; no query | no | yes | source-derived |
| ui | `ui-events` | `body.items` | source-derived | the conversation's recorded events: none before the message, then the message's `MessageEvent` (`sdk:openhands/sdk/conversation/impl/local_conversation.py:2041-2043`); each item is `ui-message-event` | the conversation's state | no | yes | source-derived |
| ui | `ui-events` | `body.next_page_id` | source-derived | `as:openhands/agent_server/event_service.py:680`, `:689-690` (`null` while the events fit one page) | no `page_id`; the log within one page | no | yes | source-derived |
| ui | `ui-events` | `fixture` | label | the fixture's label, naming the source-derived fields |  | no | yes |  |
| ui | `ui-message-event` | `kind`, `source`, `llm_message.role`, `llm_message.content[].type` | source-derived | `sdk:openhands/sdk/conversation/impl/local_conversation.py:2041-2043`, `sdk:openhands/sdk/event/llm_convertible/message.py:32-35`, `sdk:openhands/sdk/llm/message.py:177-179`, `:222-226` (a user message recorded as `MessageEvent`, source `user`, role `user`, text parts) | a user message the conversation received | no | yes | source-derived |
| ui | `ui-message-event` | `llm_message.content[].text` | source-derived | `sdk:openhands/sdk/conversation/impl/local_conversation.py:2041-2043` (the message's own text) | the message the conversation received (the dispatcher's) | no | yes | source-derived |
| ui | `ui-message-event` | `id`, `timestamp`, `<every other MessageEvent field>` | none | not served: unobserved and not required (`MessageEvent` requires `source`, `llm_message` and `kind`) |  | no | no |  |
| ui | `ui-socket` | `fixture` | label | the fixture's label, on the session socket's handshake |  | no | yes |  |
| ui | `ui-sync` | `body.type`, `body.through_seq` | source-derived | `as:openhands/agent_server/session_protocol.py:51-68`, `as:openhands/agent_server/session_socket.py:400-404` (one `sync` frame first, `through_seq` the last event's seq or `null`) | the conversation's events | no | yes | source-derived |
| ui | `ui-sync` | `body.from_seq` | echo | the request's `after_seq` | the request | no | yes |  |
| ui | `ui-sync` | `fixture` | label | the fixture's label (the handshake's) |  | no | yes |  |
| ui | `ui-durable` | `body.type`, `body.seq` | source-derived | `as:openhands/agent_server/session_protocol.py:71-81`, `as:openhands/agent_server/session_socket.py:295-312`, `:406-411` (a `durable` frame for each event above `after_seq`, `seq` its index) | the conversation's events and the request's `after_seq` | no | yes | source-derived |
| ui | `ui-durable` | `body.event` | source-derived | the event, `ui-message-event` | the conversation's events | no | yes | source-derived |
| ui | `ui-durable` | `fixture` | label | the fixture's label (the handshake's) |  | no | yes |  |
| ui | `ui-unauthorized` | `status` | observation | E-01.3.3 §8.3 step (4), PASS live at §9.1 (the conversation's inner server refuses a request without its credential); S-01.3.1 §3.4 (`401`) | a key-gated route of the face with no key or a key not the face's | no | yes |  |
| ui | `ui-unauthorized` | `body.detail` | observation | S-01.3.1 §3.4 (`{"detail": "Unauthorized"}`) | as `status`; the inner server is the same release (`as:openhands/agent_server/dependencies.py:27-39`) | no | yes |  |
| ui | `ui-unauthorized` | `fixture` | label | the fixture's label |  | no | yes |  |
| ui | `ui-socket-unauthorized` | `close.code`, `close.reason` | observation | S-01.3.1 §3.4 (WebSocket, no auth message or a wrong key in it: handshake 101, then close 4001 "Authentication failed") | a first frame that is not the face's authentication | no | yes |  |
| ui | `ui-socket-denied` | `status` | observation | S-01.3.1 §3.4 (WebSocket, a wrong key in the query or header: handshake 403) | a key in the query or header not the face's | no | yes |  |
| ui | `ui-socket-denied` | `fixture` | label | the fixture's label |  | no | yes |  |
| both | `socket-refusal` | `close.code`, `close.reason` | label | the fixture's refusal on a socket: close 1008, the reason `FIXTURE_NO_OBSERVATION` and why (an inbound message on the read-only face, a socket outside the catalog, a conversation it does not hold) |  | no | yes |  |
| both | `socket-refusal` | `fixture` | label | the fixture's label, on the handshake |  | no | yes |  |
| ui | `ui-preflight` | `status` | source-derived | `as:openhands/agent_server/middleware.py:34-50` (the pinned server answers a CORS preflight through Starlette's CORSMiddleware: 200 for an origin it allows) | a preflight of a UI route for GET from a configured origin (the engineering manager's ruling 2 of E-01.7's review); its CORS headers are the listener's own policy, as the label header is, not fields of an answer | no | yes | source-derived |
| ui | `ui-preflight` | `fixture` | label | the fixture's label, naming the source-derived field |  | no | yes |  |
| ui | `ui-settings` | `status` | source-derived | `as:openhands/agent_server/settings_router.py:118-119` (the route answers `SettingsResponse`), `as:openhands/agent_server/settings_router.py:150-153` (from `PersistedSettings()` when none is persisted) | the route (no input): a server that persists no settings, as the fixture persists none | no | yes | source-derived |
| ui | `ui-settings` | `body.agent_settings.mcp_config` | source-derived | `as:openhands/agent_server/persistence/models.py:179` (the default agent settings), `sdk:openhands/sdk/settings/model.py:2341-2347` (`OpenHandsAgentSettings()`), `sdk:openhands/sdk/settings/model.py:1603-1604` (`mcp_config` defaults to `{}`), dumped at `as:openhands/agent_server/settings_router.py:171-173` | the route (no input): a server that persists no settings, as the fixture persists none | no | yes | source-derived |
| ui | `ui-settings` | `body.agent_settings.<every other AgentSettings field>` | none | not served: unobserved at the UI's vantage and not required (the locked `SettingsResponse` requires `mcp_config` alone of `agent_settings`) |  | no | no |  |
| ui | `ui-settings` | `body.conversation_settings` | source-derived | `as:openhands/agent_server/persistence/models.py:180-182` (`ConversationSettings()` by default), dumped as an object at `as:openhands/agent_server/settings_router.py:174-176` | the route (no input): a server that persists no settings, as the fixture persists none | no | yes | source-derived |
| ui | `ui-settings` | `body.conversation_settings.<every ConversationSettings field>` | none | not served: unobserved at the UI's vantage and not required (the locked `SettingsResponse`'s `conversation_settings` is an object with no required property) |  | no | no |  |
| ui | `ui-settings` | `body.llm_api_key_is_set` | source-derived | `as:openhands/agent_server/persistence/models.py:212-222` (`False` unless the agent's `llm.api_key` holds a value), `sdk:openhands/sdk/settings/model.py:528-531` (the default LLM is built with its model alone), `sdk:openhands/sdk/llm/llm.py:289-290` (`api_key` defaults to `None`) | the route (no input): a server that persists no settings, as the fixture persists none | no | yes | source-derived |
| ui | `ui-settings` | `body.<every other SettingsResponse field>` | none | not served: unobserved at the UI's vantage and not required (`SettingsResponse` requires `agent_settings`, `conversation_settings` and `llm_api_key_is_set`) |  | no | no |  |
| ui | `ui-settings` | `fixture` | label | the fixture's label, naming the source-derived fields |  | no | yes |  |
| both | `malformed` | `status` | label | the fixture's refusal of a body it cannot parse (not JSON, or parsing but nested deeper than 64 levels): `400` (E-01.7's review, N-d and its second round) |  | no | yes |  |
| both | `malformed` | `fixture` | label | the fixture's label, with the reason it refused |  | no | yes |  |

**Source-derived entries** are on the UI face only, but for the core's one dispatcher-face entry (`message-event`),
which the listener refuses to serve. Their observed counterparts are U-03.2's (planning's re-homing).

**Not verified here:** Agent Canvas against the UI face (G5, slice 13); the "finished with a result" path over the
listener (E-01.8); every source-derived field live (U-03.2, and E-01.6 for `message-event`).

## Not here

A composition root's use of the core and the served fixture, the exchange delivery and the fixture profile: E-01.8
(slice 11). Agent Canvas against the UI face: U-01.2 (slice 13). **Not yet verified** live: every source-derived field
and the non-empty events page (E-01.6; U-03.2 for the UI face).

## The composition (E-01.8)

`run.py` is the composition root of plan leaf E-01.8 (the I1 design's slice 11; the engineering manager's rulings of
E-01.8): one ready task dispatched through the production resolver, admission, launch gate, attempt run, result
intake and result path, on the fixture transport, every seam declaring the authority `fixture` (decision 0026 points 1
and 2). `run(request, ...)` takes every seam from its caller, and in this order:

0. reads the commissioning user's identity as P-01.3's capture reads it (`capture.project_config` of
   `components.owner_host`, `capture.capture_identities(config, capture.OWNER_PRINCIPAL)`): author and committer of
   the result commit (decision 0028). An absent or invalid identity is refused with capture's own codes before
   anything is read, called or written; so is a missing result target (`RESULT_TARGET_UNCONFIGURED`) and a project
   repository that is not the request's (`PROJECT_NOT_REQUESTED`);
1. runs `recover` first (decision 0027): `DISPATCHER_BUSY`, or any held row, stops the run with that code;
2. dispatches (`dispatch_inputs.dispatch`) on the checked-in fixture profile `fixture-d1-replay` and the fixture pin
   `fixture-d1-implement`, the native execution kind replayed with the fixture credential provider's public-seed token
   (R10);
3. runs the attempt (`attempt_run.run_attempt`) with the production launch gate over the recorded inspect source as
   its `inspect`, the fixture's exchange pull, the result journal's hook and the identity: the intake takes the
   fixture's cited recorded result (PB-4) through `parse_result` and `intake_result`, unchanged;
4. publishes the result (`result_path.publish_result`) to the injected Gitea target.

`backend.py` holds the other seams, each declaring `fixture`: `FixtureCredentials` (the native token's entry and the
builder bot's, values derived from public seeds, never written), `RecordedInspect` (the core's cited
`container-inspect`), `Declared` and `Puller` (the exchange pull over `tools/guest.py`'s retained verifier).

Every record the attempt causes carries the authority `fixture` (R11): the attempt's transitions, the launch receipt,
the turn journal, the delivery, pull and intake receipts, the result journal and its receipt, the Owner report and the
pull request body; the end and stop records when an attempt is ended. The reservation itself carries its binding (the
pinned allowlist's digest in its policy inputs), so that no fixture attempt can be read as live.

**The command** (`run.py dispatch --work-id ID --repository ID`) refuses `RESULT_TARGET_UNCONFIGURED` and composes
nothing: the demonstration's result target (a fake Gitea, its listener, census port and matrix edge, or something
else) is decided at U-06.1 (the engineering manager's ruling 4 of E-01.8), with the execution window.

**The import census.** The production result path binds `integrations/credentials/credential_provider.py` at its own
import (`gitea_host`'s module-level `credentials = windows.credentials`), so the composition root loads that one
credential module, from there, and no other; no provider is constructed in a run (a construction census over
`select_provider`, `qualify_keyring` and the provider classes), no Windows credential library is loaded and no keyring
module imported (an audit hook), so the native token's entry is never reached. `tests/test_dispatch.py` holds the
proof (its run needs `AIEH_LOCKED_OPENAPI`).
