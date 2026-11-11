"""The protection check (protection_check.py; decision 0012 point 6; Owner decision OA-16), offline.

Against the fake Gitea 28.3.0 of protection_fake.py, called in memory with gitea_host.http_get's signature
(no socket), and once over an in-process HTTP server on 127.0.0.1 for the keep-alive session and the
command line. Covered: the closed list pinned to 28.3.0; verified on the fixture-equal fake with a stable
digest; drift for each of the 34 fields of each of the three rules, an extra or missing rule, rule
precedence (a shadowing rule, Gitea's own effective rule, ties), every repository setting, the roster, the
permissions, the teams and a deploy key; unverified for an unknown or missing field of every view, a failed,
lost, non-JSON or wrongly shaped read of every route, an invalid credential (missing, another account's,
not token-shaped, rejected by Gitea, the wrong scopes or account) and an auditor that is not a repository
administrator; the session's fixed GETs; no token in any verdict. Every value is synthetic.
"""
from __future__ import annotations

import contextlib
import http.server
import importlib.util
import io
import json
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


PC = _load('aieh_gitea_protection_check', HERE.parent / 'protection_check.py')
PF = _load('aieh_gitea_protection_fake', HERE / 'protection_fake.py')
R, G = PC.roles, PC.host
REPOSITORY, BASE, PORT = PF.REPOSITORY, 'main', 3000


class Provider:
    """A fixture credential provider (get only); ``reads`` lists the entry names read."""

    def __init__(self, entries):
        self.entries, self.reads = dict(entries), []

    def get(self, name):
        self.reads.append(name)
        return self.entries.get(name)


def audit_provider(token=PF.AUDIT_TOKEN, user=PF.AUDITOR):
    return Provider({PC.ENTRY: (user, token)})


class Check(unittest.TestCase):
    def setUp(self):
        self.gitea = PF.ProtectionGitea(R)
        self.provider = audit_provider()

    def verify(self, repository=REPOSITORY, base=BASE):
        verdict = PC.verify(self.provider, PORT, repository, base, http=self.gitea)
        self.assertIn(verdict.status, PC.VERDICTS)
        text = json.dumps(verdict._asdict())
        for token in self.gitea.tokens:
            self.assertNotIn(token, text)  # never the token, in any answer
        self.assertIsNone(re.search(r'(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])', text.replace('c' * 40, '')))
        if verdict.status == 'unverified':
            self.assertIsNone(verdict.digest)
        else:
            self.assertRegex(verdict.digest, r'^sha256:[0-9a-f]{64}$')
        return verdict

    def assertVerdict(self, status, code, *fragments):
        verdict = self.verify()
        self.assertEqual((verdict.status, verdict.code), (status, code), verdict.detail)
        for fragment in fragments:
            self.assertTrue(any(fragment in p for p in verdict.problems), (fragment, verdict.problems))
        return verdict


class ClosedList(unittest.TestCase):
    category = 'contract'

    # Gitea 28.3.0 modules/structs/repo_branch.go BranchProtection, its JSON names in order
    BRANCH_PROTECTION = (
        'branch_name', 'rule_name', 'priority', 'enable_push', 'enable_push_whitelist', 'push_whitelist_usernames',
        'push_whitelist_teams', 'push_whitelist_deploy_keys', 'enable_force_push', 'enable_force_push_allowlist',
        'force_push_allowlist_usernames', 'force_push_allowlist_teams', 'force_push_allowlist_deploy_keys',
        'enable_merge_whitelist', 'merge_whitelist_usernames', 'merge_whitelist_teams', 'enable_bypass_allowlist',
        'bypass_allowlist_usernames', 'bypass_allowlist_teams', 'enable_status_check', 'status_check_contexts',
        'required_approvals', 'enable_approvals_whitelist', 'approvals_whitelist_username',
        'approvals_whitelist_teams', 'block_on_rejected_reviews', 'block_on_official_review_requests',
        'block_on_codeowner_reviews', 'block_on_outdated_branch', 'dismiss_stale_approvals', 'ignore_stale_approvals',
        'require_signed_commits', 'protected_file_patterns', 'unprotected_file_patterns',
        'block_admin_merge_override', 'created_at', 'updated_at')

    def test_the_fields_are_gitea_28_3_0s(self):
        self.assertEqual(len(self.BRANCH_PROTECTION), 37)
        self.assertEqual(PC.FIELDS, tuple(f for f in self.BRANCH_PROTECTION
                                          if f not in ('branch_name', 'created_at', 'updated_at')))
        self.assertEqual(len(PC.FIELDS), 34)
        self.assertEqual(PC.RULE_KEYS, frozenset(self.BRANCH_PROTECTION))
        self.assertEqual(len(PC.REPOSITORY_KEYS), 70)
        self.assertLessEqual(set(R.repository_settings()), PC.REPOSITORY_KEYS)
        self.assertEqual(set(PF.repository_view({})) | PC.REPOSITORY_OPTIONAL, set(PC.REPOSITORY_KEYS))

    def test_the_declaration_is_total_and_deterministic(self):
        one, two = PC.declaration(REPOSITORY, BASE), PC.declaration(REPOSITORY, BASE)
        self.assertEqual(one, two)
        for rule in one['rules']:
            self.assertEqual(tuple(rule), PC.FIELDS)
        self.assertEqual(one['collaborators'][PC.AUDITOR], 'admin')
        self.assertEqual(one['teams'], {'Owners': 'owner'})
        self.assertEqual(one['deploy_keys'], [])
        self.assertEqual(PC.SCOPES, list(R.ROLES['protection-audit']['scopes']))
        for repository, base in ((REPOSITORY.upper(), BASE), ('other/repo', BASE), (REPOSITORY, 'work/x')):
            with self.subTest(repository=repository, base=base), self.assertRaises(PC.Unverifiable) as caught:
                PC.declaration(repository, base)
            self.assertEqual(caught.exception.code, 'NOT_DECLARED')


class Verified(Check):
    def test_the_fixture_as_declared_is_verified_with_a_stable_digest(self):
        one = self.assertVerdict('verified', 'VERIFIED')
        self.assertEqual(one.problems, ())
        self.assertIn("main enforces 'main'", one.detail)
        self.assertEqual(self.verify().digest, one.digest)
        self.assertEqual(self.provider.reads, [PC.ENTRY, PC.ENTRY])

    def test_null_lists_and_their_order_change_nothing(self):
        digest = self.verify().digest
        for rule in self.gitea.rules:
            for field in PC.LIST_FIELDS:
                rule[field] = None if not rule[field] else list(reversed(rule[field]))
        self.assertEqual(self.assertVerdict('verified', 'VERIFIED').digest, digest)

    def test_a_merge_changes_no_observed_value(self):
        digest = self.verify().digest
        self.gitea.repo.update(updated_at='2026-11-11T00:00:00Z', open_pr_counter=0, size=30)
        for rule in self.gitea.rules:
            rule['updated_at'] = '2026-11-11T00:00:00Z'
        self.assertEqual(self.verify().digest, digest)

    def test_only_the_fixed_reads_are_sent_with_the_token(self):
        self.verify()
        repo = f'/repos/{REPOSITORY}'
        self.assertEqual([r['path'] for r in self.gitea.requests], [
            '/token', repo, f'{repo}/branch_protections', f'{repo}/branches/main',
            f'{repo}/collaborators?page=1&limit=50',
            *(f'{repo}/collaborators/{user}/permission' for user in R.collaborators()),
            f'{repo}/teams', f'{repo}/keys?page=1&limit=50'])
        self.assertEqual({(r['method'], r['auth'], r['doer']) for r in self.gitea.requests},
                         {('GET', 'token', PC.AUDITOR)})


class FieldDrift(Check):
    @staticmethod
    def changed(field, value):
        if isinstance(value, bool):
            return not value
        if isinstance(value, int):
            return value + 7
        if isinstance(value, list):
            return [*value, 'aieh-intruder']
        return value + 'x'

    def test_each_field_of_each_rule(self):
        names = [r['rule_name'] for r in R.protection_rules()]
        for name in names:
            for field in PC.FIELDS:
                with self.subTest(rule=name, field=field):
                    self.setUp()
                    rule = self.gitea.rule(name)
                    rule[field] = self.changed(field, rule[field])
                    if field == 'rule_name':
                        rule['branch_name'] = '' if PF.special(rule['rule_name']) else rule['rule_name']
                        self.assertVerdict('drift', 'DRIFT', f'the declared rule {name!r} is missing',
                                           f'rule {rule["rule_name"]!r}')
                    else:
                        self.assertVerdict('drift', 'DRIFT', f'{name}.{field} is ')

    def test_the_bypass_allowlist(self):
        main = self.gitea.rule('main')
        main.update(enable_bypass_allowlist=True, bypass_allowlist_usernames=['aieh-bot-builder'],
                    bypass_allowlist_teams=['Owners'])
        verdict = self.assertVerdict('drift', 'DRIFT', 'main.enable_bypass_allowlist is True, declared False',
                                     "main.bypass_allowlist_usernames is ['aieh-bot-builder'], declared []",
                                     "main.bypass_allowlist_teams is ['Owners'], declared []")
        self.assertEqual(len(verdict.problems), 3)

    def test_the_digest_follows_the_observed_state(self):
        before = self.verify().digest
        self.gitea.rule('**')['required_approvals'] = 2
        changed = self.verify().digest
        self.gitea.rule('**')['required_approvals'] = 0
        self.assertNotEqual(changed, before)
        self.assertEqual(self.verify().digest, before)


class RuleSetAndPrecedence(Check):
    def add_rule(self, name, priority, **settings):
        rule = R._total_rule(name, priority, **settings)
        self.gitea.rules.append(PF.rule_view(rule, 8))

    def test_an_extra_rule_that_does_not_match_main(self):
        self.add_rule('release/*', 4)
        self.assertVerdict('drift', 'DRIFT', "rule 'release/*' (priority 4) is not declared")

    def test_a_missing_rule(self):
        self.gitea.rules = [r for r in self.gitea.rules if r['rule_name'] != 'work/*']
        self.assertVerdict('drift', 'DRIFT', "the declared rule 'work/*' is missing")

    def test_a_rule_that_shadows_main(self):
        """A glob with a higher priority than main's rule is the one Gitea enforces on main."""
        self.add_rule('ma*', 0, enable_push=True)
        verdict = self.assertVerdict('drift', 'DRIFT', "rule 'ma*' (priority 0) is not declared",
                                     "the rules matching main in Gitea's order are ['ma*', 'main', '**']",
                                     "Gitea enforces the rule 'ma*' on main, declared 'main'")
        self.assertIn("'ma*'", verdict.detail)

    def test_main_s_rule_lowered_below_the_catch_all(self):
        self.gitea.rule('main')['priority'] = 5
        self.assertVerdict('drift', 'DRIFT', 'main.priority is 5, declared 1', "Gitea enforces the rule '**' on main")

    def test_without_main_s_rule_the_catch_all_is_enforced(self):
        self.gitea.rules = [r for r in self.gitea.rules if r['rule_name'] != 'main']
        self.assertVerdict('drift', 'DRIFT', "the declared rule 'main' is missing",
                           "Gitea enforces the rule '**' on main, declared 'main'")

    def test_an_unprotected_branch(self):
        self.gitea.rules = [r for r in self.gitea.rules if r['rule_name'] == 'work/*']
        self.assertVerdict('drift', 'DRIFT', 'the branch main is not protected', "Gitea enforces the rule '' on main")

    def test_a_case_variant_of_main_is_main(self):
        self.add_rule('MAIN', 0)
        self.assertVerdict('drift', 'DRIFT', "Gitea enforces the rule 'MAIN' on main")

    def test_gitea_s_effective_rule_must_be_the_one_its_order_gives(self):
        self.gitea.effective = '**'
        verdict = self.assertVerdict('unverified', 'PRECEDENCE_UNVERIFIED')
        self.assertIn("Gitea enforces '**' on main", verdict.detail)

    def test_a_glob_the_check_cannot_evaluate(self):
        self.add_rule('ma[in', 9)
        self.assertVerdict('unverified', 'PRECEDENCE_UNVERIFIED')


class Precedence(unittest.TestCase):
    """Gitea 28.3.0's rule order and matching (models/git/protected_branch_list.go, modules/glob)."""

    @staticmethod
    def rule(name, priority, created='2026-01-01T00:00:00Z'):
        return {'rule_name': name, 'priority': priority, 'created_at': created}

    def test_order_priority_then_plain_then_created(self):
        rules = [self.rule('**', 1, 'b'), self.rule('main', 1, 'c'), self.rule('m*', 1, 'a'), self.rule('*', 0, 'z')]
        self.assertEqual(PC.precedence(rules, 'main'), ['*', 'main', 'm*', '**'])
        self.assertEqual(PC.precedence([self.rule('m*', 2, 'b'), self.rule('*', 2, 'a')], 'main'), ['*', 'm*'])

    def test_matching(self):
        cases = [('main', 'main', True), ('main', 'MAIN', True), ('main', 'mainline', False),
                 ('work/*', 'work/a', True), ('work/*', 'work/a/b', False), ('work/**', 'work/a/b', True),
                 ('**', 'main', True), ('**', 'a/b', True), ('*', 'a/b', False), ('ma?n', 'main', True),
                 ('ma?n', 'ma/n', False), ('m[ai]in', 'main', True), ('m[!a]in', 'main', False),
                 ('{main,work}', 'work', True), ('{main,work}', 'other', False), ('a.b', 'aXb', False),
                 ('a\\*b', 'a*b', True), ('a\\*b', 'axb', False), ('v+1', 'v+1', True), ('a(b)', 'a(b)', True),
                 ('re[^/]*', 're^x', True), ('a[\\]]b', 'a]b', True), ('a[\\]]b', 'a\\b', False),
                 ('a[[]b', 'a[b', True), ('x{a', 'xa', None), ('x[a', 'xa', None), ('x\\', 'x', None)]
        for pattern, branch, expected in cases:
            with self.subTest(pattern=pattern, branch=branch):
                if expected is None:
                    with self.assertRaises(PC.Unverifiable) as caught:
                        PC.matches(pattern, branch)
                    self.assertEqual(caught.exception.code, 'PRECEDENCE_UNVERIFIED')
                else:
                    self.assertIs(PC.matches(pattern, branch), expected)

    def test_plain_names(self):
        self.assertTrue(PC.is_plain('main') and PC.is_plain('release-1.0'))
        for name in ('m*', 'a?', 'a\\b', 'a[b', 'a]', 'a{b', 'a}'):
            self.assertFalse(PC.is_plain(name), name)


class RepositoryDrift(Check):
    def test_each_setting(self):
        for key, value in R.repository_settings().items():
            with self.subTest(key=key):
                self.setUp()
                self.gitea.repo[key] = 'rebase' if key == 'default_merge_style' else (
                    'other' if isinstance(value, str) else not value)
                self.assertVerdict('drift', 'DRIFT', f"the repository's {key} is ")

    def test_the_roster(self):
        for change, fragment in (({'aieh-intruder': 'write'}, 'collaborator aieh-intruder: write, declared absent'),
                                 ({'aieh-bot-reviewer': 'write'}, 'collaborator aieh-bot-reviewer: write, declared read'),
                                 ({'aieh-bot-builder': 'owner'}, 'collaborator aieh-bot-builder: owner, declared write'),
                                 ({'aieh-owner': 'admin'}, 'collaborator aieh-owner: admin, declared write')):
            with self.subTest(change=change):
                self.setUp()
                self.gitea.collaborators.update(change)
                self.assertVerdict('drift', 'DRIFT', fragment)
        self.setUp()
        del self.gitea.collaborators['aieh-bot-verifier']
        self.assertVerdict('drift', 'DRIFT', 'collaborator aieh-bot-verifier: absent, declared read')

    def test_the_teams(self):
        self.gitea.teams.append(PF.team_view('Reviewers', 'write', 2))
        self.assertVerdict('drift', 'DRIFT', 'team Reviewers: write, declared absent')
        self.gitea.teams = [PF.team_view('Owners', 'admin')]
        self.assertVerdict('drift', 'DRIFT', 'team Owners: admin, declared owner')
        self.gitea.teams = []
        self.assertVerdict('drift', 'DRIFT', 'team Owners: absent, declared owner')

    def test_a_deploy_key_or_deploy_token(self):
        for key_type in ('ssh', 'token'):
            with self.subTest(key_type=key_type):
                self.setUp()
                self.gitea.keys = [{'id': 4, 'key_id': 0, 'key': '', 'url': '', 'title': 'deploy', 'key_type': key_type,
                                    'fingerprint': 'f', 'created_at': 'now', 'read_only': False}]
                self.assertVerdict('drift', 'DRIFT', f"'key_type': '{key_type}'")


class Unverified(Check):
    def test_an_unknown_or_missing_field_of_a_rule(self):
        for key in sorted(PC.RULE_KEYS):
            with self.subTest(missing=key):
                self.setUp()
                del self.gitea.rule('main')[key]
                self.assertVerdict('unverified', 'VIEW_INVALID')
        self.setUp()
        self.gitea.rule('work/*')['block_on_new_setting'] = False
        verdict = self.assertVerdict('unverified', 'VIEW_INVALID')
        self.assertIn('block_on_new_setting', verdict.detail)
        self.assertIn("branch protection rule 'work/*' has field(s)", verdict.detail)

    def test_a_field_of_another_type(self):
        for field, value in (('enable_push', 'false'), ('priority', True), ('priority', '1'),
                             ('push_whitelist_usernames', 'aieh-bot-builder'), ('merge_whitelist_usernames', [1]),
                             ('protected_file_patterns', None), ('rule_name', None)):
            with self.subTest(field=field, value=value):
                self.setUp()
                self.gitea.rule('main')[field] = value
                self.assertVerdict('unverified', 'VIEW_INVALID')

    def test_an_inconsistent_branch_name_or_repeated_rule(self):
        self.gitea.rule('**')['branch_name'] = '**'
        self.assertVerdict('unverified', 'VIEW_INVALID')
        self.setUp()
        self.gitea.rules.append(dict(self.gitea.rule('main')))
        self.assertVerdict('unverified', 'VIEW_INVALID')
        self.setUp()
        self.gitea.rules.append('not an object')
        self.assertVerdict('unverified', 'VIEW_INVALID')

    def test_an_unknown_or_missing_field_of_every_other_view(self):
        for view, mutate in (('repository unknown', lambda g: g.repo.update(allow_new_merge_style=True)),
                             ('repository missing', lambda g: g.repo.pop('allow_squash_merge'))):
            with self.subTest(view=view):
                self.setUp()
                mutate(self.gitea)
                self.assertVerdict('unverified', 'VIEW_INVALID')
        for route in ('token', 'branch', 'permission', 'teams'):
            for kind in ('unknown', 'missing'):
                with self.subTest(route=route, kind=kind):
                    self.setUp()
                    original = self.gitea._handle

                    def handle(method, path, headers, body, route=route, kind=kind, original=original):
                        status, headers_, data = original(method, path, headers, body)
                        if self.route_of(path) != route:
                            return status, headers_, data
                        payload = json.loads(data)
                        items = payload if isinstance(payload, list) else [payload]
                        for item in items:
                            if kind == 'unknown':
                                item['an_unknown_field'] = True
                            else:
                                item.pop(sorted(item)[0])
                        return status, headers_, json.dumps(payload).encode()

                    self.gitea._handle = handle
                    self.assertVerdict('unverified', 'VIEW_INVALID')

    @staticmethod
    def route_of(path):
        path = path.removeprefix('/api/v1')
        if path == '/token':
            return 'token'
        rest = path.removeprefix(f'/repos/{REPOSITORY}')
        return {'': 'repository', '/branch_protections': 'rules', '/teams': 'teams'}.get(rest) or (
            'branch' if rest.startswith('/branches/') else 'permission' if rest.endswith('/permission') else
            'collaborators' if rest.startswith('/collaborators') else 'keys')

    def test_a_failed_or_lost_read_of_every_route(self):
        for route in PF.ROUTES:
            for fault in (403, 404, 500, 'not-json', 'wrong-kind', 'drop'):
                with self.subTest(route=route, fault=fault):
                    self.setUp()
                    self.gitea.faults[route] = fault
                    verdict = self.assertVerdict('unverified', 'READ_FAILED')
                    if fault == 'drop':
                        self.assertIn('the answer was lost (ConnectionResetError)', verdict.detail)
                    if isinstance(fault, int):  # Gitea's message is part of the detail
                        self.assertIn(f'answered {fault} (a fault of the fake ({fault}))', verdict.detail)

    def test_a_list_not_read_whole(self):
        for route in ('collaborators', 'keys'):
            with self.subTest(route=route):
                self.setUp()
                self.gitea.faults[route] = 'no-total'
                self.assertVerdict('unverified', 'VIEW_INVALID')
        self.setUp()
        self.gitea.collaborators['aieh-intruder!'] = 'read'
        self.assertVerdict('unverified', 'VIEW_INVALID')

    def test_a_team_or_permission_out_of_gitea_s_values(self):
        self.gitea.teams = [PF.team_view('Owners', 'superuser')]
        self.assertVerdict('unverified', 'VIEW_INVALID')
        self.setUp()
        self.gitea.teams = [PF.team_view('Owners', 'owner'), PF.team_view('Owners', 'owner', 2)]
        self.assertVerdict('unverified', 'VIEW_INVALID')
        self.setUp()
        self.gitea.teams = ['not an object']
        self.assertVerdict('unverified', 'VIEW_INVALID')
        self.setUp()
        self.gitea.collaborators['aieh-bot-planner'] = 'superuser'
        self.assertVerdict('unverified', 'VIEW_INVALID')

    def test_the_repository_answers_as_another(self):
        self.gitea.repo['full_name'] = 'aieh-authz-fixture/renamed'
        self.assertVerdict('unverified', 'VIEW_INVALID')

    def test_a_branch_view_of_another_type(self):
        original = self.gitea._handle

        def handle(method, path, headers, body):
            status, headers_, data = original(method, path, headers, body)
            if '/branches/' in path:
                payload = json.loads(data)
                payload['protected'] = 'yes'
                data = json.dumps(payload).encode()
            return status, headers_, data

        self.gitea._handle = handle
        self.assertVerdict('unverified', 'VIEW_INVALID')


class Credential(Check):
    def test_refused_before_anything_is_sent(self):
        for name, entries, code in (
                ('missing', {}, 'CREDENTIAL_MISSING'),
                ('another account', {PC.ENTRY: (PF.OWNER, PF.AUDIT_TOKEN)}, 'CREDENTIAL_REFUSED'),
                ('a password', {PC.ENTRY: (PF.AUDITOR, 'a-password-not-a-token')}, 'CREDENTIAL_REFUSED'),
                ('an upper-case token', {PC.ENTRY: (PF.AUDITOR, PF.AUDIT_TOKEN.upper())}, 'CREDENTIAL_REFUSED'),
                ('an empty secret', {PC.ENTRY: (PF.AUDITOR, '')}, 'CREDENTIAL_REFUSED')):
            with self.subTest(entry=name):
                self.setUp()
                self.provider = Provider(entries)
                verdict = self.assertVerdict('unverified', code)
                self.assertEqual(self.gitea.requests, [])
                self.assertEqual(self.provider.reads, [PC.ENTRY])
                self.assertNotIn('a-password-not-a-token', verdict.detail)

    def test_an_undeclared_repository_reads_nothing(self):
        verdict = self.verify(repository='other/repo')
        self.assertEqual((verdict.status, verdict.code), ('unverified', 'NOT_DECLARED'))
        self.assertEqual((self.gitea.requests, self.provider.reads), ([], []))

    def test_a_token_gitea_rejects(self):
        self.provider = audit_provider(token='e' * 40)
        verdict = self.assertVerdict('unverified', 'CREDENTIAL_REJECTED')
        self.assertEqual(len(self.gitea.requests), 1)
        self.assertNotIn('e' * 40, verdict.detail)

    def test_the_wrong_scopes_or_account(self):
        for name, change in (('write:repository', {'scopes': ['write:repository']}), ('all', {'scopes': ['all']}),
                             ('one scope more', {'scopes': ['read:repository', 'read:user']}),
                             ('no scope', {'scopes': []}), ('scopes not a list', {'scopes': 'read:repository'}),
                             ('another bot', {'login': PF.VERIFIER})):
            with self.subTest(token=name):
                self.setUp()
                self.gitea.tokens[PF.AUDIT_TOKEN].update(change)
                self.assertVerdict('unverified', 'AUDITOR_INVALID')
                self.assertEqual(len(self.gitea.requests), 1)

    def test_the_verifier_s_token_in_the_auditor_s_entry(self):
        self.provider = audit_provider(token=PF.VERIFIER_TOKEN)
        verdict = self.assertVerdict('unverified', 'AUDITOR_INVALID')
        self.assertIn(PF.VERIFIER, verdict.detail)

    def test_an_auditor_that_is_not_a_repository_administrator(self):
        for permission in ('write', 'read'):
            with self.subTest(permission=permission):
                self.setUp()
                self.gitea.collaborators[PF.AUDITOR] = permission
                verdict = self.assertVerdict('unverified', 'AUDITOR_INVALID')
                self.assertIn('not a repository administrator', verdict.detail)
                self.assertFalse(any('branch_protections' in r['path'] for r in self.gitea.requests))


class Session(unittest.TestCase):
    def test_nothing_but_the_fixed_reads(self):
        gitea = PF.ProtectionGitea(R)
        session = PC.AuditSession(PORT, PF.AUDIT_TOKEN, REPOSITORY, BASE, gitea)
        repo = f'/repos/{REPOSITORY}'
        for method, path in (('POST', '/token'), ('DELETE', '/token'), ('PATCH', f'{repo}/branch_protections/main'),
                             ('GET', f'{repo}/branch_protections/main'), ('GET', '/user'), ('GET', '/admin/users'),
                             ('GET', f'{repo}/collaborators'), ('GET', f'{repo}/collaborators?page=2&limit=50'),
                             ('GET', f'{repo}/branches/work'), ('GET', '/repos/other/repo'),
                             ('GET', f'{repo}/collaborators/a b/permission'), ('GET', f'{repo}/hooks'),
                             ('PUT', f'{repo}/collaborators/{PF.AUDITOR}'), ('GET', '/token?sudo=aieh-owner')):
            with self.subTest(method=method, path=path), self.assertRaises(ValueError):
                session.request(method, path)
        self.assertEqual(gitea.requests, [])
        self.assertEqual(session.get('/token')[0], 200)
        session.close()
        with self.assertRaises(ValueError):
            session.get('/token')
        self.assertEqual(len(gitea.requests), 1)

    def test_an_unusable_repository_or_branch_name(self):
        for repository, base in (('a/b/c', 'main'), ('../x', 'main'), (REPOSITORY, '../main'), (REPOSITORY, '')):
            with self.subTest(repository=repository, base=base), self.assertRaises(ValueError):
                PC.AuditSession(PORT, PF.AUDIT_TOKEN, repository, base)


# ---------------------------------------------------------------------------- over loopback


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.server.connections += 1

    def do_GET(self):  # noqa: N802
        answer = self.server.gitea.handle('GET', self.path, dict(self.headers.items()), None)
        if answer is PF.DROP:
            self.close_connection = True
            return
        status, headers, data = answer
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        if self.server.close_each:
            self.send_header('Connection', 'close')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        if self.server.silent_close:  # closes the connection without saying so, as an idle timeout does
            self.close_connection = True

    def log_message(self, *args):  # quiet
        pass


class Loopback(unittest.TestCase):
    """The session's own keep-alive connection, over an in-process HTTP server on 127.0.0.1."""
    category = 'integration'

    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        cls.httpd.daemon_threads = True
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def setUp(self):
        self.httpd.gitea = PF.ProtectionGitea(R)
        self.httpd.connections, self.httpd.close_each, self.httpd.silent_close = 0, False, False

    def verify(self):
        return PC.verify(audit_provider(), self.port, REPOSITORY, BASE)

    def test_one_keep_alive_connection_per_check(self):
        verdict = self.verify()
        self.assertEqual(verdict.status, 'verified', verdict.detail)
        self.assertEqual(self.httpd.connections, 1)
        self.assertEqual(len(self.httpd.gitea.requests), 13)

    def test_a_server_that_closes_after_each_answer(self):
        self.httpd.close_each = True
        self.assertEqual(self.verify().status, 'verified')
        self.assertEqual(self.httpd.connections, 13)

    def test_a_closed_session_holds_no_connection(self):
        session = PC.AuditSession(self.port, PF.AUDIT_TOKEN, REPOSITORY, BASE)
        self.assertEqual(session.get('/token')[0], 200)
        self.assertIsNotNone(session._connection)
        session.close()
        self.assertIsNone(session._connection)

    def test_a_lost_answer_on_a_new_connection_is_not_sent_again(self):
        """Only a read on a connection the server closed while idle is sent once more; a fresh connection's
        lost answer is unverified."""
        self.httpd.gitea.faults['token'] = 'drop-once'
        verdict = self.verify()
        self.assertEqual((verdict.status, verdict.code), ('unverified', 'READ_FAILED'))
        self.assertEqual(len(self.httpd.gitea.requests), 1)

    def test_a_lost_answer(self):
        self.httpd.gitea.faults['teams'] = 'drop'
        verdict = self.verify()
        self.assertEqual((verdict.status, verdict.code), ('unverified', 'READ_FAILED'))
        self.assertIn('the answer was lost', verdict.detail)

    def test_a_connection_gitea_closed_while_idle_is_read_once_more(self):
        self.httpd.silent_close = True
        session = PC.AuditSession(self.port, PF.AUDIT_TOKEN, REPOSITORY, BASE)
        try:
            self.assertEqual(session.get('/token')[0], 200)
            self.assertEqual(session.get('/token')[0], 200)
        finally:
            session.close()
        self.assertEqual(self.httpd.connections, 2)
        self.assertEqual(len(self.httpd.gitea.requests), 2)

    def test_the_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        provider = audit_provider()
        with mock.patch.object(G, 'credential_provider',
                               side_effect=lambda: G.contract.WatchedProvider(provider, G.ACT_GUARD)):
            code = PC.main(['verify', REPOSITORY, '--port', str(self.port)], out=out, err=err)
            self.assertEqual(code, 0, err.getvalue())
            report = json.loads(out.getvalue())
            self.assertEqual((report['status'], report['code']), ('verified', 'VERIFIED'))
            self.assertIn('I7 no-exposure scan: clean (1 secrets held', err.getvalue())
            self.httpd.gitea.rule('main')['enable_push'] = True
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(PC.main(['verify', REPOSITORY, '--port', str(self.port)], out=out, err=err), 1)
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(PC.main(['verify', 'other/repo', '--port', str(self.port)], out=out, err=err), 2)
            self.assertEqual(json.loads(out.getvalue())['code'], 'NOT_DECLARED')
        self.assertIsNone(G.ACT_GUARD)
        self.assertNotIn(PF.AUDIT_TOKEN, out.getvalue() + err.getvalue())

    def test_the_command_line_refuses_an_exposed_token(self):
        out, err = io.StringIO(), io.StringIO()
        provider = audit_provider()
        leaky = PC.Verdict('drift', 'DRIFT', f'holding {PF.AUDIT_TOKEN}')

        def verify(prov, *args, **kwargs):
            prov.get(PC.ENTRY)
            return leaky

        with mock.patch.object(G, 'credential_provider',
                               side_effect=lambda: G.contract.WatchedProvider(provider, G.ACT_GUARD)), \
                mock.patch.object(PC, 'verify', side_effect=verify):
            code = PC.main(['verify', REPOSITORY, '--port', str(self.port)], out=out, err=err)
        self.assertEqual((code, out.getvalue()), (1, ''))
        self.assertIn('EXPOSURE_FOUND', err.getvalue())
        self.assertNotIn(PF.AUDIT_TOKEN, err.getvalue())

    def test_the_command_line_without_a_managed_gitea(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(G.paths, 'resolve', side_effect=G.paths.PathsError('DEFAULT_ROOT_UNAVAILABLE', 'no managed root')):
            code = PC.main(['verify', REPOSITORY], out=out, err=err)
        self.assertEqual((code, out.getvalue()), (2, ''))
        self.assertIn('protection-check:', err.getvalue())
        with mock.patch.object(G, 'credential_provider',
                               side_effect=G.GiteaError('NO_CREDENTIAL_PROVIDER', 'none here')):
            out, err = io.StringIO(), io.StringIO()
            code = PC.main(['verify', REPOSITORY, '--port', str(self.port)], out=out, err=err)
        self.assertEqual((code, out.getvalue()), (2, ''))
        self.assertIn('NO_CREDENTIAL_PROVIDER', err.getvalue())


if __name__ == '__main__':
    unittest.main()
