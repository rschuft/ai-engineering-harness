"""An in-memory stand-in for the integration store's receipts (integrations/store/integration_store.py), for
the offline tests of the credential acts' receipts (plan leaf F-06.3): reserve, transition, get and events,
with the store's states and allowed transitions, and the intent and detail kept as canonical JSON. The real
store is exercised by integrations/credentials/tests against a fixture database."""
from __future__ import annotations

import json
from types import SimpleNamespace

TRANSITIONS = {('reserved', 'dispatched'), ('reserved', 'failed'), ('dispatched', 'confirmed'),
               ('dispatched', 'failed'), ('dispatched', 'unknown'), ('unknown', 'confirmed'), ('unknown', 'failed')}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class FakeReceipts:
    def __init__(self, fail_reserve: bool = False, corrupt_detail: bool = False):
        self.records, self.log = {}, {}
        self.fail_reserve, self.corrupt_detail = fail_reserve, corrupt_detail

    def reserve(self, key, intent, *, actor):
        if self.fail_reserve:
            raise OSError('the receipt store is unavailable')
        assert key not in self.records, key
        self.records[key] = SimpleNamespace(operation_key=key, intent_json=canonical(intent), state='reserved')
        self.log[key] = [SimpleNamespace(seq=0, from_state=None, to_state='reserved', actor=actor, reason=None,
                                         detail_json=None)]
        return SimpleNamespace(reservation=self.records[key], created=True)

    def transition(self, key, to_state, *, actor, reason=None, detail=None, expected_from=None):
        record = self.records[key]
        if expected_from is not None and record.state != expected_from:
            raise ValueError(f'{key} is {record.state}, not {expected_from}')
        if (record.state, to_state) not in TRANSITIONS:
            raise ValueError(f'{record.state} -> {to_state}')
        detail_json = None if detail is None else canonical(detail)
        if self.corrupt_detail and to_state == 'confirmed':
            detail_json = canonical({'tampered': True})
        self.log[key].append(SimpleNamespace(seq=len(self.log[key]), from_state=record.state, to_state=to_state,
                                             actor=actor, reason=reason, detail_json=detail_json))
        record.state = to_state
        return record

    def get(self, key):
        return self.records.get(key)

    def events(self, key):
        return list(self.log.get(key, []))

    def states(self) -> dict:
        """{operation key: its states in order}."""
        return {key: [event.to_state for event in events] for key, events in self.log.items()}

    def text(self) -> str:
        """Everything the receipts hold, as text (for the no-secret assertions)."""
        return ''.join(r.intent_json for r in self.records.values()) + ''.join(
            e.detail_json or '' for events in self.log.values() for e in events)
