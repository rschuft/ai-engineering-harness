# The Owner conversation store (`integrations/conversation/`)

Plan leaf **U-01.3** (the store and its session table); U-02.1 adds threads and messages.
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
| `tests/test_conversation_store.py` | Identity and refusal of other kinds, the migration ledger, locations, the session table's rules (unit) |

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

## Use

```python
store = open_store(path)                    # creates or migrates; refuses another kind, an altered schema, the
                                            # checkout, a network path
store.enroll_session(session_id=..., verifier=..., issued_at=..., expires_at=...)   # enroll only
store.session_by_verifier(verifier)         # a Session (current or not), or None; reads only
store.canonical_dump()                      # deterministic bytes of every canonical table
```

There is no command line: the ownerhost commands open it. Backup and restore are not decided (decision 0025, "Not
decided here"): the kind's `after_restore` refuses.

## Commands

```
<tools python> -I -B -m unittest discover -s integrations/conversation/tests -v   # task conversation:test
```

## Not yet verified

- Threads and messages (U-02.1), the lineage resolver over them (U-02.2).
- Backup and restore of this store (not decided).
