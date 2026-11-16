# The Agent Server fixture's cited core (E-01.4.2, slice 5c)

The one fixture catalog that E-01.7's served fixture will serve (slice 9), and the core that answers from it. In this
slice the core answers **in process only**, on the dispatcher's face, and only tests import it: no listener, no served
fixture, no UI face and no composition root uses it yet.

- `observations.json`: the catalog. Each answer is an entry; each field of each entry has its provenance class, its
  citation, the inputs that determine it, whether the dispatch path reads it, whether it is served, and its marks.
- `core.py`: `AgentServerCore`, which answers a dispatcher request by its route **and the conversation's state**, from
  the catalog only. A request outside the catalog, or one whose answer would need a field of no class, is refused with
  the fixture's label. It records every request it receives in its call log (what the fake received). Standard
  library only.
- The provenance table below. A test binds it to `observations.json` row for row, and the read-binding test binds its
  **Read** column to what the dispatch path reads.

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
| F-04.2 §4.1 to §4.9 | [evidence/F-04.2-conversation-lifecycle.md](../../evidence/F-04.2-conversation-lifecycle.md), section 4 (run A, `f042-a`): 4.1 the fixture and the routes, 4.2 create, 4.3 inspect, 4.4 the persisted events, 4.6 stop, 4.9 delete |
| F-04.1c §3 | [evidence/F-04.1c-agent-server.md](../../evidence/F-04.1c-agent-server.md), section 3 (run 1, `f041c-a`): `/server_info` as returned (complete), and `/api/conversations/count` (body `0`) |
| D1 §5 | [evidence/D1-run-2026-11-16.md](../../evidence/D1-run-2026-11-16.md), section 5: the steps (2), (3), (4), (6), (7b), (9), (10) and "The dispatcher's calls" (method, path, status of every call) |

Every observation in this catalog is cited to one of these. None needed the E-01.3.x or S-01.3.1 evidence: S-01.3.1's
refused create is E-01.7's failed scenario (slice 9), not an answer E-01.4.2 uses.

## The pinned upstream source (the source-derived entry, and the events page's determining inputs)

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

## The provenance table

One row per field. **Read**: the dispatch path reads it (bound by the read-binding test). **Served**: the core puts a
value in the answer. Paths: `status`, `body.<key>`, `[]` for each element of a list; `fixture` is the label.

| Answer | Field | Class | Citation | Determined by | Read | Served | Marks |
|---|---|---|---|---|---|---|---|
| `server-info` | `status` | observation | F-04.1c §3; F-04.2 §4.1; D1 §5 calls | the route (no input) | yes | yes | |
| `server-info` | `body.version` | observation | F-04.1c §3; F-04.2 §4.1 | the server's build | yes | yes | |
| `server-info` | `body.capabilities` | observation | F-04.1c §3 (F-04.2 §4.1 names two of them) | the server's build | yes | yes | |
| `server-info` | `body.conversation_runtime` | observation | F-04.1c §3; F-04.2 §4.1 | the profile's server configuration | yes | yes | |
| `server-info` | `body.available_conversation_runtimes` | observation | F-04.1c §3; F-04.2 §4.1 | the profile's server configuration | yes | yes | |
| `server-info` | `body.uptime` | observation | F-04.1c §3 | the clock | no | yes | clock-valued |
| `server-info` | `body.idle_time` | observation | F-04.1c §3 | the clock | no | yes | clock-valued |
| `server-info` | `body.app_backend_ingress_url` | observation | F-04.1c §3 | the profile's server configuration | no | yes | |
| `server-info` | `body.build_git_ref` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.build_git_sha` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.docs` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.max_foreground_terminal_timeout_seconds` | observation | F-04.1c §3 | the profile's server configuration | no | yes | |
| `server-info` | `body.python_version` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.redoc` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.runtime_idle_timeout_seconds` | observation | F-04.1c §3 | the profile's server configuration | no | yes | |
| `server-info` | `body.sdk_version` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.title` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.tools_version` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.usable_tools` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `body.workspace_version` | observation | F-04.1c §3 | the server's build | no | yes | |
| `server-info` | `fixture` | label | the fixture's label | | no | yes | |
| `create-new` | `status` | observation | F-04.2 §4.2; D1 §5 (2) | a valid create whose `conversation_id` the server does not hold | yes | yes | |
| `create-new` | `body.id` | echo | the request's `conversation_id` | the request | yes | yes | |
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
| `conversation` | `status` | observation | F-04.2 §4.3; D1 §5 (3), (6) | a conversation the server holds | yes | yes | |
| `conversation` | `body.id` | echo | the request path's `conversation_id` | the request | yes | yes | |
| `conversation` | `body.execution_status` | observation | `idle`: F-04.2 §4.3 (a created conversation, no message); `finished`: D1 §5 (6) (its turn ended) | the conversation's state | yes | yes | |
| `conversation` | `body.<every other ConversationInfo field>` | none | not served: no committed observation of its value | | no | no | |
| `conversation` | `fixture` | label | the fixture's label | | no | yes | |
| `conversation-absent` | `status` | observation | F-04.2 §4.9 (`GET` after the delete: 404) | a conversation the server does not hold | yes | yes | |
| `conversation-absent` | `body.detail` | none | not served: F-04.2 §4.9 records the status only | | no | no | |
| `conversation-absent` | `fixture` | label | the fixture's label | | no | yes | |
| `count` | `status` | observation | F-04.1c §3; D1 §5 (3), (10) | the route (no input) | yes | yes | |
| `count` | `body` | observation | `0`: F-04.1c §3, D1 §5 (10); `1`: D1 §5 (3) | the number of conversations the server holds (0 or 1; any other number is refused) | yes | yes | |
| `count` | `fixture` | label | the fixture's label | | no | yes | |
| `runtime` | `status` | observation | F-04.2 §4.3, §4.6; D1 §5 (3), (9) | a conversation the server holds | yes | yes | |
| `runtime` | `body.runtime_status` | observation | `available`: F-04.2 §4.3, D1 §5 (3) (after the create); `missing`: F-04.2 §4.6, D1 §5 (9) (after the runtime stop) | the conversation's state | yes | yes | |
| `runtime` | `body.can_resume` | observation | F-04.2 §4.3, §4.6; D1 §5 (3) | the conversation's state (`true` in both) | no | yes | |
| `runtime` | `fixture` | label | the fixture's label | | no | yes | |
| `runtime-stop` | `status` | observation | F-04.2 §4.6; D1 §5 calls (`DELETE .../runtime` 204) | a held conversation whose runtime is `available` | yes | yes | |
| `runtime-stop` | `body` | observation | F-04.2 §4.6; D1 §5 calls: `204` No Content, so the transport's body is `null` | the status | yes | yes | see the note below the readings |
| `runtime-stop` | `fixture` | label | the fixture's label | | no | yes | |
| `seed` | `status` | observation | D1 §5 calls (`POST .../bash/execute_bash_command` 200, SEED) and (4) | the harness's SEED command, the first on a held conversation | yes | yes | |
| `seed` | `body.stdout` | pinned-rule | `integrations/dispatch/attempt_run.py` `SEED_SCRIPT`, run over the request's payload (its success line `AIEH-SEED ok <sha256> <files>`) | the request's payload and digest | yes | yes | |
| `seed` | `body.exit_code` | pinned-rule | `integrations/dispatch/attempt_run.py` `SEED_SCRIPT`, run over the request's payload | the request's payload and digest | yes | yes | |
| `seed` | `body.stderr` | none | not served: not observed, and not read | | no | no | |
| `seed` | `fixture` | label | the fixture's label | | no | yes | |
| `message` | `status` | observation | D1 §5 calls (`POST .../events` 200, the message) | the message tail, the first on a held conversation | yes | yes | |
| `message` | `body` | none | not served: not observed (D1's call list records the status only) | | no | no | |
| `message` | `fixture` | label | the fixture's label | | no | yes | |
| `events` | `status` | observation | F-04.2 §4.4 | a held conversation; no query | yes | yes | |
| `events` | `body.items` | observation | F-04.2 §4.4 (`[]` on an empty log); on a non-empty log, the catalog's events (`message-event`) | the conversation's recorded events | yes | yes | |
| `events` | `body.next_page_id` | observation | F-04.2 §4.4 (`null`) | no `page_id`, and the log within one page at the effective limit (`as:openhands/agent_server/event_router.py:76-79`, `as:openhands/agent_server/event_service.py:689-690`) | yes | yes | engineering manager's reading |
| `events` | `fixture` | label | the fixture's label | | no | yes | |
| `message-event` | `kind` | observation | D1 §5 (7b) (`MessageEvent` in the log of a conversation that received the dispatcher's message) | the event's type | yes | yes | |
| `message-event` | `source` | source-derived | `sdk:openhands/sdk/conversation/impl/local_conversation.py:2041-2043`; `sdk:openhands/sdk/event/llm_convertible/message.py:32` | a user message sent to the conversation | yes | yes | source-derived |
| `message-event` | `llm_message` | source-derived | `sdk:openhands/sdk/event/llm_convertible/message.py:33-35`; `as:openhands/agent_server/event_router.py:226` | the message | yes | yes | source-derived |
| `message-event` | `llm_message.content` | source-derived | `sdk:openhands/sdk/llm/message.py:226`; `as:openhands/agent_server/event_router.py:226` | the request's `content` | yes | yes | source-derived |
| `message-event` | `llm_message.content[].text` | echo | the request's `content[].text` (`sdk:openhands/sdk/llm/message.py:179`) | the request | yes | yes | source-derived |
| `message-event` | `id`, `timestamp`, `llm_message.role`, `llm_message.content[].type`, `llm_response_id`, `activated_skills`, `extended_content`, `sender`, `critic_result` | none | not served: no committed observation, and not read | | no | no | |
| `refusal` | `status` | label | the fixture's refusal: `501` | | no | yes | |
| `refusal` | `fixture` | label | the fixture's label, with the reason it refused | | no | yes | |

**Not served**, by answer: `create-new`, every top-level field but those listed served (and, for a request that is not
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
3. **RESULT** (engineering manager's reading, 2026-11-16): no observation covers this catalog's RESULT, so it is
   refused with the label; in the restart matrix's rows J, K and L the row's "then" is that `resume_result` reaches
   exactly one RESULT, refused, and the row's verdict rests on the create and message counts and the turn state.
4. **Classes** (engineering manager's reading, 2026-11-16): as in the table. `running` is not served; the restart
   matrix's row L dies at the wait's first read, a listed transport event (the request never arrives).
5. **Knobs** (engineering manager's reading, 2026-11-16): every behaviour of the existing fakes outside the catalog
   stays in its test module as a subclass or wrapper (below). `CountingTransport` (`test_dispatch_admission.py`) is
   not one of the three fakes and is out of scope.

**The engineer's classing, for the engineering manager's review:** the `runtime-stop` answer's `body`. A `204`
carries no content; the dispatch path's answer helper (`attempt_end._answer`) reads the answer's `body` key and
`stop_runtime` discards it. It is classed as a consequence of the observed status (`null`, the transport's body for no
content), not as a value of its own.

## The core's behaviour by state

The core holds, per conversation: whether it exists, its execution status (`idle` after its create, `finished` once
its message is received), its runtime status (`available` after the create, `missing` after the runtime stop),
whether it was seeded, and its events (the `message-event` once the message is received). Its scenarios advance by
the requests it receives, never by a clock. It has no clock, no route that reaches a guest, a model or a credential,
and no listener.

| Request | Condition | Answer |
|---|---|---|
| `GET /server_info` | always | `server-info` |
| `POST /api/conversations` | a `conversation_id` it does not hold | `create-new` (the conversation now held) |
| `GET /api/conversations/count` | 0 or 1 held | `count` |
| `GET /api/conversations/{id}` | held / not held | `conversation` / `conversation-absent` |
| `GET .../runtime` | held | `runtime` |
| `DELETE .../runtime` | held, runtime `available` | `runtime-stop` (runtime now `missing`) |
| `POST .../bash/execute_bash_command` | the harness's SEED command, the conversation held and not yet seeded | `seed` |
| `POST .../events` | the message tail, the conversation held, no message yet | `message` (the `message-event` recorded; status `finished`) |
| `GET .../events/search` | held, no query | `events` |
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

## Not here

The listener, the served fixture and its scenarios, the UI face, the network matrix and inventory rows: E-01.7
(slice 9). A composition root's use of the core: slice 11. **Not yet verified** live: every source-derived field and
the non-empty events page (E-01.6).
