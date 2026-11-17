# The Agent Server fixture's cited core (E-01.4.2, slice 5c; the container inspect, E-01.5)

The one fixture catalog that E-01.7's served fixture will serve (slice 9), and the core that answers from it. In this
slice the core answers **in process only**, on the dispatcher's face, and only tests import it: no listener, no served
fixture, no UI face and no composition root uses it yet.

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
| `conversation` | `status` | observation | F-04.2 §4.3; D1 §5 (3), (6) | a conversation the server holds | yes: `attempt_end._answer`, `reconcile._lookup`, `reconcile.verdict_of`, `restart_recovery._lookup_reserved` | yes | |
| `conversation` | `body.id` | echo | the request path's `conversation_id` | the request | yes: `attempt_end.observe`, `attempt_run.inspect_conversation`, `reconcile.verdict_of` | yes | |
| `conversation` | `body.execution_status` | observation | `idle`: F-04.2 §4.3 (a created conversation, no message); `finished`: D1 §5 (6) (its turn ended) | the conversation's state; `finished` by the fixture's transition on the message (no turn runs) | yes: `attempt_end._finished`, `attempt_end.observe`, `attempt_run.conversation_status` | yes | scenario: the core's transition (by call count) |
| `conversation` | `body.<every other ConversationInfo field>` | none | not served: no committed observation of its value | | no | no | |
| `conversation` | `fixture` | label | the fixture's label | | no | yes | |
| `conversation-absent` | `status` | observation | F-04.2 §4.9 (`GET` after the delete: 404); a conversation never created answers alike, neither having a record or an event service (`as:openhands/agent_server/conversation_router.py:229-231`, `as:openhands/agent_server/conversation_service.py:1136-1143`; the delete leaves none: `as:openhands/agent_server/docker_runtime/routers.py:336-342`, `as:openhands/agent_server/conversation_service.py:984-989`) | a conversation the server does not hold | yes: `reconcile._lookup`, `reconcile.verdict_of`, `restart_recovery._lookup_reserved` | yes | |
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
`execution_status`; `conversation-absent`, its body; `seed`, `stderr`; `message`, its body; `message-event`, every
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

## Not here

The listener, the served fixture and its scenarios, the UI face, the network matrix and inventory rows: E-01.7
(slice 9). A composition root's use of the core: slice 11. **Not yet verified** live: every source-derived field and
the non-empty events page (E-01.6).
