# The Owner conversation store (`integrations/conversation/`)

Plan leaf **U-01.3** (the store and its session table) and **U-02.1** (threads and messages, migration 0002).
[Decision 0025](../../decisions/0025-integration-process-owner-ui-session-credential-and-owner-conversation-store.md)
(accepted at U-01.3's verdict), points 3 and 6. Python standard library only (`sqlite3`), on the shared mechanics of
[`integrations/storecore`](../storecore/storecore.py).

`conversation.sqlite` is a store kind of its own, at `<state>/owner-host/conversation.sqlite` of the managed data
root (decision 0009), never tables in `integration.sqlite`: the integration store "is not a record of authority",
while this store becomes the lineage authority for the `conversation` and `message` kinds. It is written only by the
Integration process ([`integrations/ownerhost`](../ownerhost/README.md)) and, for sessions, by the Owner's `enroll`
command.

## Files

| Path | What |
|---|---|
| `conversation_store.py` | The store kind (`KIND`, `application_id` `0x41494356`, 'AICV'), `open_store`, `ConversationStore` |
| `migrations/0001_store_identity_and_sessions.sql` | The store's identity, the migration ledger and the `owner_session` table with its triggers |
| `migrations/0002_threads_and_messages.sql` | The `thread`, `thread_event`, `message` and `message_revision` tables and their append-only triggers (U-02.1) |
| `tests/test_conversation_store.py` | Identity and refusal of other kinds, the migration ledger, locations, the session table's rules (unit) |
| `tests/test_threads_and_messages.py` | U-02.1's proof at the store level: reload, repeats, refusals, the triggers, assistant revisions, quotes cut with `lineage.span_reference` (unit) |

## Migration 0001

- `PRAGMA application_id = 0x41494356`: the integration and effects stores refuse this file, and it refuses theirs.
- `schema_migration`: one row per applied migration with the sha256 of its LF-normalised text; an edited migration
  is refused at open.
- `owner_session`: one row per enrollment of `cred-owner-ui-session`: `seq`, `session_id` (a public UUID version 4),
  `verifier` (64 hexadecimal digits: the sha256 of the domain line and the credential; never the credential),
  `issued_at`, `expires_at` (`YYYY-MM-DDTHH:MM:SSZ`, after the issue time and at most 7 days later) and
  `supersedes`. SQLite's triggers and constraints enforce, for any writer that leaves them in place: no update and
  no delete; a new row supersedes exactly the current session (the last row), the first none; a verifier and a
  session id are used once.

They are not a boundary against a process of the Owner's account, which can drop a trigger, rewrite rows or replace
the file (decision 0010 point 1, the accepted same-account limit). `open_store` makes the first visible: it refuses a
store whose schema objects, triggers included, are not exactly what its migrations create
(`SchemaAltered`, code `CONVERSATION_STORE_ALTERED`), so neither the Integration process nor `enroll` starts on it. A
writer that keeps the schema and changes rows is not detected here.

The current session is the last row; a session another row supersedes is revoked. An expired session is kept, so
that expired and foreign stay distinguishable.

## Migration 0002: threads and messages (U-02.1)

Decision 0025, point 6. The backend of the Owner UI shell's two assistant-ui adapters, written only by the
Integration process ([`integrations/ownerhost`](../ownerhost/README.md)) on the Owner's authenticated request; every
row names the session that wrote it.

| Table | What | Rules (SQLite triggers and constraints) |
|---|---|---|
| `thread` | One row per thread: `seq`, `thread_id` (a UUID version 4 the store mints), `session_id`, `local_id` (assistant-ui's `__LOCALID_...`), `created_at` | `seq` is the next number; (`session_id`, `local_id`) is unique, so a repeated initialize finds its thread; no update, no delete |
| `thread_event` | A title (`rename`) or the archive state (`archive`, `unarchive`); the latest of each kind is current | `seq` is the next number; no update, no delete |
| `message` | One row per message: `thread_id`, `message_id` (assistant-ui's native id, seven characters of `[0-9A-Za-z]`), `seq` (the store's per-thread order), `parent_id` (a message of the same thread, or none), `role`, `author` (`owner` for a user message, `owner-host` for an assistant message), `session_id`, `created_at` (a user message's, as the shell sent it), `appended_at` | (`thread_id`, `message_id`) is unique; `seq` is the thread's next number; the parent is already stored; no update, no delete |
| `message_revision` | A message's content by revision, with its sha256: a user message's text as UTF-8 bytes exactly as received (no normalization, no trimming); an assistant message as canonical JSON | the revision is the message's next number; a user message has revision 1 only (immutable); at most 256 KiB; no update, no delete |

`open_store` also checks that each stored content matches its recorded sha256 and that a user message's bytes are
UTF-8, and refuses an altered schema (`CONVERSATION_STORE_ALTERED`): a dropped, replaced or added trigger, table or
index. A writer of the Owner's account that keeps the schema and rewrites a content and its digest is the
same-account limit (decision 0010 point 1); a span anchor cut before such a change then fails
(`SPAN_DIGEST_MISMATCH`, `tests/test_threads_and_messages.py` `Quotes`).

| Operation | Rule | Refusal (nothing changed) |
|---|---|---|
| `initialize_thread` | The thread for (session, local id), minted once | `THREAD_INVALID` |
| `rename_thread`, `archive_thread`, `unarchive_thread` | An event, when it changes the current value | `THREAD_INVALID`, `THREAD_NOT_FOUND` |
| `delete_thread` | Always refused: nothing is deleted; archive instead | `THREAD_DELETE_REFUSED` |
| `append_message` | assistant-ui's `append`: the message under the next `seq`; the same id with the same parent, role and content is a repeat that adds nothing | `MESSAGE_INVALID`, `MESSAGE_PARENT_NOT_FOUND`, `MESSAGE_ID_CONFLICT` |
| `update_message` | assistant-ui's `update`, an upsert for assistant messages (a new revision; an unknown one is appended); a user message's same bytes change nothing | `MESSAGE_IMMUTABLE`, `MESSAGE_NOT_FOUND` (an update never creates a user message), `MESSAGE_ID_CONFLICT` |
| `load` | Every message at its latest revision in `seq` order, as assistant-ui's history items (with `seq` beside each), no head | `THREAD_NOT_FOUND` |
| `message_content` | A message's durable bytes: for an Owner statement, the source every quote is cut from | `MESSAGE_NOT_FOUND` |

A user message is accepted only as the composer sends it: one text part (not empty, no NUL, encodable as UTF-8, so
no lone surrogate), its `createdAt`, no attachments, empty custom metadata. An edit in assistant-ui is a new message
under the same parent: both are kept, and the branch the Owner sees after a reload is the newest (the load answers
no head).

## Use

```python
store = open_store(path)                    # creates or migrates; refuses another kind, an altered schema, the
                                            # checkout, a network path
store.enroll_session(session_id=..., verifier=..., issued_at=..., expires_at=...)   # enroll only
store.session_by_verifier(verifier)         # a Session (current or not), or None; reads only
thread, created = store.initialize_thread(session_id=..., local_id='__LOCALID_...', at=...)
store.append_message(thread.thread_id, {'parentId': None, 'message': {...}}, session_id=..., at=...)
store.load(thread.thread_id)                # {'messages': [{seq, parentId, message}, ...]}
store.message_content(thread_id, message_id)  # the durable bytes a quote is cut from
store.canonical_dump()                      # deterministic bytes of every canonical table
```

There is no command line: the ownerhost commands open it. Backup and restore are not decided (decision 0025, "Not
decided here"): the kind's `after_restore` refuses.

## Commands

```
<tools python> -I -B -m unittest discover -s integrations/conversation/tests -v   # task conversation:test
```

## Not yet verified

- U-02.1's verdict (built 2026-11-16; its tests PASS offline); the lineage resolver over the store (U-02.2).
- The Owner's own conversation with his own session in a real browser.
- Backup and restore of this store (not decided).
