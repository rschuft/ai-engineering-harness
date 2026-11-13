"""The real-key containment search (plan leaf S-03.3, slice 4; the slice plan's D-5 as accepted by the engineering
manager: the search reads the key from the same credential entry the broker reads, same account, decision 0010
point 1 and decision 0013 point 6, in memory only).

S-03.3's proof asks that the real provider key be searched for at its exposure boundaries, raw and encoded, by a
checker that holds it in memory only and reports counts, with a positive control, never printing or persisting it
(fingerprint-only is not proof of absence). inference_key_search.py is that checker for the synthetic key, read
from standard input. This module is its real-key mode, as a separate command so that the key search itself stays
independent of the broker: no person pipes the key. It is read here, once, from the credential provider entry the
broker reads ("AIEH model provider", through the broker's own credential factory, credentials.select_provider, the
provider the broker's managed context uses), held in memory, refused unless its fingerprint is the one given (the
running broker's, from its start receipt or status), and handed to inference_key_search.run: the same forms, views,
surfaces and positive controls (copies planted by the standard library's encoders), the same verdicts, and the
same withheld-report rule. The report adds the entry, the provider's name and the Owner's act, never the key.

Its live use is covered only by the Owner's act A1 (OA-12: the provider key in its Credential Manager entry): the
command refuses to run without --owner-act naming that act, and reads nothing before every argument is checked.
--owner-act is a label that names the act in the report: its grammar is checked, but it is not checked against any
record (no recorded Owner act is read or verified here); that the act exists is the operator's statement.
It reads no standard input and no environment variable, prints and writes no copy of the key, and keeps no log.

  <tools python> -I -B integrations/inference/inference_real_key_search.py search --owner-act ACT \\
      --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]

KIND is file, tree, tar or environ (PATH self), as in inference_key_search.py. Exit 0 not-found, 1 found, invalid
or incomplete (or a withheld report), 2 refused (a stable code). Standard library only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent


def _load(name: str, path: Path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


broker = _load('aieh_inference_broker', HERE / 'inference_broker.py')
ks = _load('aieh_inference_key_search', HERE / 'inference_key_search.py')

FORMAT = 'aieh-inference-real-key-search/1'
MISMATCH_REMEDY = ('give --expect-fingerprint as the running broker\'s provider-key fingerprint (its start receipt or '
                   'status); the entry holds another key')
OWNER_ACT = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._:()/-]{0,63}')
CODES = {
    'OWNER_ACT_REQUIRED': 'name the Owner\'s act that covers reading the provider key (A1 of OA-12) with --owner-act: '
                          'a letter or digit, then up to 63 letters, digits, spaces or ._:()/-',
    'KEY_PROVIDER_FAILED': 'the credential provider did not answer: run as the account the broker runs as, where its '
                           'credential provider is available',
    'KEY_ENTRY_ABSENT': 'store the provider key first (inference_broker.py credential-set, the Owner\'s act A1): the '
                        'entry "AIEH model provider" holds no key',
}


class RealKeyError(Exception):
    """A refusal (exit 2) with a stable code of CODES and its remedy; never the key."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail, self.remedy = code, detail, CODES[code]
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


def check_owner_act(value) -> str:
    if not isinstance(value, str) or not OWNER_ACT.fullmatch(value):
        raise RealKeyError('OWNER_ACT_REQUIRED', 'no act named, or not in its grammar')
    return value


def read_entry_key(expected: str, provider_factory: Callable) -> tuple[str, str]:
    """(key, provider name): the key of the broker's credential entry, from PROVIDER_FACTORY's provider, held in
    memory and refused unless its fingerprint is EXPECTED. No message repeats what was read."""
    try:
        provider = provider_factory()
        entry = provider.get(broker.ENTRY)
        source = broker.credentials.describe(provider)['provider']
    except Exception as exc:  # noqa: BLE001 - any provider failure: its type only, never what it read
        raise RealKeyError('KEY_PROVIDER_FAILED', f'{type(exc).__name__}') from None
    if not isinstance(entry, (tuple, list)) or len(entry) != 2 or not isinstance(entry[1], str) or not entry[1]:
        raise RealKeyError('KEY_ENTRY_ABSENT', f'the entry {broker.ENTRY!r} holds no provider key')
    key = entry[1]
    del entry
    try:
        ks.check_fingerprint(key, expected)
    except ks.SearchError as exc:          # this caller's meaning: the entry's key, never a piped one
        if exc.code != 'FINGERPRINT_MISMATCH':
            raise
        mismatch = ks.SearchError(exc.code, 'the key of the credential entry is not the key of that fingerprint')
        mismatch.remedy = MISMATCH_REMEDY
        mismatch.args = (f'{mismatch.code}: {mismatch.detail}. Remedy: {MISMATCH_REMEDY}.',)
        raise mismatch from None
    return key, str(source)[:64]


def run(owner_act: str, expected: str, surfaces: list, provider_factory: Callable) -> dict:
    """Search SURFACES ([(label, kind, path)]) for the key of the broker's entry (inference_key_search.run), under
    OWNER_ACT; the report never holds the key (OUTPUT_WITHHELD)."""
    key, source = read_entry_key(expected, provider_factory)
    try:
        report = ks.run(key, expected, surfaces)
        report['format'], report['search_format'] = FORMAT, report['format']
        report['key'].update({'entry': broker.ENTRY, 'source': source, 'owner_act': owner_act,
                              'read': 'from the credential provider entry the broker reads, through the broker\'s '
                                      'credential factory; held in memory only; never from standard input'})
        if ks.Search(key).holds(json.dumps(report, sort_keys=True)):
            raise ks.SearchError('OUTPUT_WITHHELD', 'the report held the key')
        return report
    finally:
        del key


def main(argv=None, out=None, err=None, provider_factory: Callable | None = None) -> int:
    parser = argparse.ArgumentParser(prog='inference_real_key_search.py', description='The real-key containment '
                                     'search (S-03.3 slice 4): the key of the broker\'s credential entry, held in '
                                     'memory, raw and in its encodings, on the listed surfaces, with a positive '
                                     'control. Only under the Owner\'s act A1. Exit 0 not-found, 1 found, invalid or '
                                     'incomplete, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('search', help='read the key of the broker\'s credential entry and search the surfaces')
    search.add_argument('--owner-act', required=True, help='a label naming the Owner\'s act that covers reading the '
                                                           'key (A1); recorded in the report, not checked against '
                                                           'any record')
    search.add_argument('--expect-fingerprint', required=True,
                        help="the running broker's provider-key fingerprint (start receipt or status), "
                             'sha256:<16 hex digits>')
    search.add_argument('--surface', action='append', required=True, dest='surfaces',
                        help='LABEL=KIND:PATH, KIND file, tree, tar or environ (PATH self); repeatable')
    args = parser.parse_args(argv)
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        act = check_owner_act(args.owner_act)
        surfaces = [ks.parse_surface(value) for value in args.surfaces]
        if len({label for label, _, _ in surfaces}) != len(surfaces):
            raise ks.SearchError('SURFACE_INVALID', 'each label once')
        if not ks.FINGERPRINT.fullmatch(args.expect_fingerprint):
            raise ks.SearchError('FINGERPRINT_INVALID', 'not sha256:<16 hex digits>')
        report = run(act, args.expect_fingerprint, surfaces, provider_factory or broker.credentials.select_provider)
    except (RealKeyError, ks.SearchError) as exc:
        err.write(f'inference-real-key-search: {exc}\n')
        return 1 if exc.code == 'OUTPUT_WITHHELD' else 2
    out.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
    err.write(f"inference-real-key-search: {report['verdict']}: {report['bytes_searched']} bytes on "
              f"{len(report['surfaces'])} surface(s); controls {'valid' if report['controls']['valid'] else 'INVALID'}"
              f" ({report['controls']['cases']} cases); key {report['key']['fingerprint']} from "
              f"{report['key']['source']} under {report['key']['owner_act']!r}\n")
    return 0 if report['verdict'] == 'not-found' else 1


if __name__ == '__main__':
    sys.exit(main())
