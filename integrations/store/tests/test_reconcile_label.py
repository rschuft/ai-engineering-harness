"""Tests for reconcile's optional ``label`` (plan leaf E-01.8; the engineering manager's ruling (a) on the review's
STOP: the transitions the store's reconcile writes carry the attempt's bound authority when its caller gives one).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/store/tests -p test_reconcile_label.py -v

``IntegrationStore.reconcile(oracle, actor=, label=)``: given ``label``, each transition reconcile writes (the restore
epoch's ``dispatched -> unknown``, ``unknown -> confirmed``, ``unknown -> failed``) has ``detail=label(reservation)``;
without it, or when it returns an empty mapping, the detail is NULL, as before. A label that raises is called before
its transition: that attempt is not moved and the exception propagates, as an oracle's does (the transitions already
written stay, each its own transaction): reconcile's existing behaviour.
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent / 'integration_store.py'
_spec = importlib.util.spec_from_file_location('integration_store', MODULE)
store_mod = sys.modules.get('integration_store')
if store_mod is None:
    store_mod = importlib.util.module_from_spec(_spec)
    sys.modules['integration_store'] = store_mod
    _spec.loader.exec_module(store_mod)

INTENT = {'scoped_resources': {'repository': 'example/repo'}, 'request': {'agent': 'builder'}}
LABEL = {'authority': 'fixture'}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-reconcile-label-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = self.tmp / 'integration.sqlite'

    def open(self):
        store = store_mod.open_store(self.db)
        self.addCleanup(store.close)
        return store

    def unknown(self, store, key, n=0):
        store.reserve(key, {**INTENT, 'n': n}, actor='t')
        store.transition(key, 'dispatched', actor='t')
        store.transition(key, 'unknown', actor='t')

    def details(self, store, key):
        return [(e.to_state, None if e.detail_json is None else json.loads(e.detail_json))
                for e in store.events(key)]


class Labels(Case):
    category = 'unit'

    def test_the_label_is_the_detail_of_confirmed_and_failed(self):
        store = self.open()
        self.unknown(store, 'op-found', 1)
        self.unknown(store, 'op-gone', 2)
        verdicts = {'op-found': 'performed', 'op-gone': 'not_performed'}
        report = store.reconcile(lambda r: verdicts[r.operation_key], actor='r', label=lambda r: dict(LABEL))
        self.assertEqual((report['confirmed'], report['failed']), (['op-found'], ['op-gone']))
        self.assertEqual(self.details(store, 'op-found')[-1], ('confirmed', LABEL))
        self.assertEqual(self.details(store, 'op-gone')[-1], ('failed', LABEL))

    def test_no_label_or_an_empty_one_leaves_the_detail_null(self):
        for label in (None, lambda r: {}):
            with self.subTest(label=label):
                store = self.open()
                key = f'op-{label is None}'
                self.unknown(store, key)
                store.reconcile(lambda r: 'performed', actor='r', label=label)
                [last] = store.events(key)[-1:]
                self.assertEqual((last.to_state, last.detail_json), ('confirmed', None))

    def test_a_label_that_raises_moves_nothing_of_that_attempt_and_propagates(self):
        store = self.open()
        self.unknown(store, 'op-a', 1)
        self.unknown(store, 'op-b', 2)

        def label(reservation):
            if reservation.operation_key == 'op-b':
                raise RuntimeError('the label cannot be read')
            return dict(LABEL)
        with self.assertRaises(RuntimeError):
            store.reconcile(lambda r: 'performed', actor='r', label=label)
        states = {key: store.get(key).state for key in ('op-a', 'op-b')}
        moved = [k for k, s in states.items() if s == 'confirmed']
        self.assertEqual(store.get('op-b').state, 'unknown', 'the attempt whose label raised is not moved')
        self.assertEqual(self.details(store, 'op-b')[-1], ('unknown', None))
        for key in moved:   # a transition written before the raise stays, as after an oracle's raise
            self.assertEqual(self.details(store, key)[-1], ('confirmed', LABEL))


class RestoreEpoch(Case):
    category = 'integration'

    def test_the_restore_epochs_sweep_carries_the_label_too(self):
        store = self.open()
        store.reserve('op-x', INTENT, actor='t')
        store.transition('op-x', 'dispatched', actor='t')
        manifest = store.backup(actor='owner')
        store.close()
        store_mod.restore_store(self.db, self.db.parent / 'backups' / (manifest['backup_file'] + '.manifest.json'),
                                actor='owner')
        restored = self.open()
        restored.reconcile(lambda r: 'performed', actor='r', label=lambda r: dict(LABEL))
        self.assertEqual(self.details(restored, 'op-x')[-2:], [('unknown', LABEL), ('confirmed', LABEL)])


if __name__ == '__main__':
    unittest.main()
