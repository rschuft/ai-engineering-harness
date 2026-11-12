"""Check the CI runner control profile and the CI token and secret policy (plan leaf Q-02.1).

``policy/ci-runner-profile.json`` specifies the hostile-CI lanes of decision 0016 (Proposed):
the validation lane (the CI guest's runner and its disposable job containers) and the trusted
promotion lane, the runner's placement and declared configuration, its single path to Gitea
(the ``ci-control`` forward, an Owner act), the Gitea-side configuration, the filtering proxy's
allowlist, the registration procedure, the governance workflow's rules and the Owner acts.
``policy/ci-token-secret-policy.json`` holds the two task tokens, the token ceilings, the secret
rules, the credential-to-lane map, the revocation rows and the Gitea Actions facts at the pin.
``policy/ci/workflows/*.yml`` is the governance workflow's source of record. ``policy/README.md``
renders them. This checker enforces the leaf's acceptance mechanically: no untrusted validation
job has any reason or configuration path to an Owner or other privileged credential, the
runner's reach to Gitea and the job token's use are decided against decision 0013 point 7, and
every forward is an Owner act.

It fails when:

- a validation lane holds a credential of owner, admin, executor or management authority, the
  validation job holds anything but the two task tokens or the runner host anything but the
  runner token, or the profile's lanes differ from the token policy's credential-to-lane map;
- an inventory credential has no lane, or a credential held in a CI domain is in another lane;
- the validation job reaches anything, or a task token reaches anything or is relied on;
- a runner-configuration invariant is missing or weakened, or a profile variant's declared
  ``config.yaml`` (``provisioning.ci_runner.config``) violates one (a ``host`` or ``lxc``
  label, environment injection, the cache, privileged mode, the engine socket, volumes, the
  host network, IPv6, pulls, a host workspace, a shared tool cache, hooks, a post-task script,
  extra headers, the metrics listener, the health check, or a ``container.options`` token
  outside the declared list) or holds ``$`` (the runner expands ``${NAME}`` from its
  environment); the variant's runner service sets a forbidden environment variable (the label
  override, the registration token, a proxy, the engine host, the job hooks, telemetry) or
  overrides the labels;
- a workflow under ``policy/ci/workflows/`` breaks decision 0016 section 7.3: a trigger other
  than ``workflow_dispatch`` with exactly the three inputs; a missing or non-empty top-level
  ``permissions:`` or any other ``permissions:``; ``uses:``; a ``secrets.`` or ``vars.``
  reference; another ``runs-on``; ``container:`` or ``services:``; any expression outside the
  job's three input variables; the first steps absent, reordered or incomplete; an allowlist
  other than the profile's; or a step key that could skip or soften a step (``if``,
  ``continue-on-error``); the subset of YAML it accepts is strict, and anything else fails;
- the Gitea section enables Actions outside the governance repository, declares a public
  repository, a token mode other than ``restricted``, a ceiling other than none, a
  cross-repository grant, a secret or variable, or an incomplete governance protection;
- the proxy allowlist is not exactly the runner RPC; the registration procedure does not reset
  the token before it is read and after registration, its fallback (a token standing between
  provisionings) is in force, or its live gate does not block a live runner until Q-02.2.2
  proves the reset invalidates the delivered value (the Owner's direction of 2026-11-10); the
  token may enter other than by ``--token-file`` from ``/run/``; or a variant's register call
  passes ``--token``, the token's environment variable or ``--labels``, omits ``--config``,
  names another instance than the ``ci-control`` endpoint, or is ephemeral other than exactly
  when the chosen lifetime is per-validation;
- an Owner act lacks its requesting leaf or claims ``observed`` without a verbatim bootstrap-log
  approval; a forward or host listener names no Owner act;
- a fact verified at source lacks its paths and lines or the archive the lock pins, a live one
  lacks evidence, or an unverified one its leaf;
- a revocation row differs from the role-token matrix's;
- an inventory, matrix, role, plan-leaf or decision id does not resolve, a statement carries no
  status or ``verify_at`` leaf, or the decision record exists but is not linked;
- a machine path appears; the README's generated block differs from ``--render``; or the
  profile's ``checks`` do not name exactly the codes this checker emits.

It needs only the standard library and reads nothing outside the repository. The live check
of the Gitea instance is not this checker's (decision 0016 section 6.6): ``--live-report`` is
an interface for the administration command's report from Q-02.3.1 and refuses to run before.

Usage (from the repository root):
    python -I -B tools/check_ci_policy.py [--root DIR] [--profile FILE] [--policy FILE]
                                          [--list] [--render]

Exit status: 0 PASS, 1 FAIL, 2 could not run.
"""
import argparse
import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'check_security_inventory', Path(__file__).resolve().parent / 'check_security_inventory.py')
csi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csi)

PROFILE_SCHEMA = 'ai-engineering-harness/policy/ci-runner-profile/v1'
POLICY_SCHEMA = 'ai-engineering-harness/policy/ci-token-secret-policy/v1'
DEFAULT_PROFILE = Path('policy') / 'ci-runner-profile.json'
DEFAULT_POLICY = Path('policy') / 'ci-token-secret-policy.json'
INVENTORY = 'security/inventory.json'
MATRIX = 'policy/network-matrix.json'
ROLE_TOKENS = 'policy/role-tokens.json'
LOCK = 'composition/lock/components.lock.json'
BOOTSTRAP_LOG = 'evidence/bootstrap-log.md'

STATUSES = ('decided', 'planned', 'observed')
ACT_STATUSES = ('planned', 'observed')
LANES = ('validation-job', 'validation-runner-host', 'trusted-lane', 'none')
PROFILE_LANES = ('validation-job', 'validation-runner-host', 'trusted-lane')
JOB_CREDENTIALS = ('cred-ci-job-token', 'cred-ci-runtime-token')
RUNNER_CREDENTIALS = ('cred-runner-token',)
LANE_OF_DOMAIN = {'td-untrusted-ci': 'validation-job', 'td-ci-runner-host': 'validation-runner-host'}
REVOCATION_REQUIRED = JOB_CREDENTIALS + RUNNER_CREDENTIALS + ('cred-runner-registration',)
UNITS = ('code', 'issues', 'pull_requests', 'packages', 'actions', 'wiki', 'releases', 'projects')
PROTECTIONS = ('every_ref_push_protected', 'main_owner_only_merge', 'admin_override_blocked')
SECRET_SETS = ('repository_secrets', 'owner_secrets', 'repository_variables', 'owner_variables',
               'instance_variables')
REACH_KINDS = ('forward', 'listener', 'existing', 'none')

# The decided runner-configuration invariants (decision 0016 section 2.3): path -> (rule, value).
REQUIRED_RULES = {
    'runner.labels': ('labels', None),
    'runner.envs': ('must_be_empty', None),
    'runner.env_file': ('must_be_empty', None),
    'runner.capacity': ('must_equal', 1),
    'runner.timeout': ('must_be_set', None),
    'cache.enabled': ('must_equal', False),
    'container.privileged': ('must_equal', False),
    'container.docker_host': ('must_equal', '-'),
    'container.valid_volumes': ('must_be_empty', None),
    'container.network': ('must_be_empty', None),
    # Not a key at the 6.0.0 pin (Overseer ruling (2), 2026-11-12): the stale key is declared
    # nowhere, and IPv6 is set off under network_create_options.
    'container.enable_ipv6': ('must_be_empty', None),
    'container.network_create_options.enable_ipv6': ('must_equal', False),
    'container.force_pull': ('must_equal', False),
    'container.force_rebuild': ('must_equal', False),
    'container.options': ('options', None),
    # The 6.0.0 keys the declaration must pin (Overseer ruling (3), 2026-11-12).
    'container.bind_workdir': ('must_equal', False),
    'container.sweep': ('must_equal', False),
    'runner.tool_cache_mode': ('must_equal', 'none'),
    'runner.hooks': ('must_be_empty', None),
    'runner.post_task_script': ('must_be_empty', None),
    'runner.extra_headers': ('must_be_empty', None),
    'metrics.enabled': ('must_equal', False),
    'health_check.enabled': ('must_equal', False),
}
# The runner process's environment (ruling (3)): names compared without case, and prefixes.
REQUIRED_ENV_NAMES = ('GITEA_RUNNER_LABELS', 'GITEA_RUNNER_REGISTRATION_TOKEN', 'HTTP_PROXY',
                      'HTTPS_PROXY', 'NO_PROXY', 'DOCKER_HOST')
REQUIRED_ENV_PREFIXES = ('ACTIONS_RUNNER_HOOK_', 'OTEL_')
# The registration token's input (ruling (5)): a file on /run, never the command line or
# the environment.
TOKEN_FLAG = '--token-file'
TOKEN_PATH_PREFIX = '/run/'
TOKEN_REFUSED = ('--token', 'GITEA_RUNNER_REGISTRATION_TOKEN')
REQUIRED_OPTIONS = ('--cap-drop=ALL', '--security-opt=no-new-privileges', '--ulimit=core=0')
REQUIRED_OPTION_PREFIXES = ('--user=', '--pids-limit=', '--memory=', '--cpus=')
# Option names that weaken the job container; the declared exchange mount and
# --security-opt=no-new-privileges are the only volume and security options admitted.
FORBIDDEN_OPTIONS = ('--privileged', '--cap-add', '--device', '--pid', '--network', '--net',
                     '--userns', '--ipc', '--uts', '--security-opt', '-v', '--volume', '--mount',
                     '--group-add', '--runtime', '--cgroupns', '--add-host')
LABEL = re.compile(r'^aieh-validation:docker://[^@\s]+@sha256:[0-9a-f]{64}$')

# The filtering proxy's allowlist (decision 0016 section 3.5): (method, path) -> window.
PROXY_ALLOW = {
    ('POST', '/api/actions/ping.v1.PingService/*'): None,
    ('POST', '/api/actions/runner.v1.RunnerService/Register'): 'provisioning',
    ('POST', '/api/actions/runner.v1.RunnerService/Declare'): None,
    ('POST', '/api/actions/runner.v1.RunnerService/FetchTask'): None,
    ('POST', '/api/actions/runner.v1.RunnerService/UpdateTask'): None,
    ('POST', '/api/actions/runner.v1.RunnerService/UpdateLog'): None,
}
PROXY_DENY = ('/api/actions_pipeline/*', '/twirp/github.actions.results.api.v1.ArtifactService/*',
              '/api/v1/*')

WORKFLOW_TOP_KEYS = {'name', 'on', 'permissions', 'jobs'}
JOB_KEYS = {'name', 'runs-on', 'timeout-minutes', 'env', 'steps'}
STEP_KEYS = {'id', 'name', 'shell', 'env', 'run', 'working-directory', 'timeout-minutes'}
EXPRESSION = re.compile(r'\$\{\{(.*?)\}\}', re.S)
SECRET_REF = re.compile(r'\b(secrets|vars)\s*(\.|\[)')
LINES = re.compile(r'^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$')
DECISION_ID = re.compile(r'^[0-9]{4}$')

PROFILE_KEYS = {'schema', 'plan_leaf', 'title', 'as_of', 'baseline_commit', 'token_policy',
                'inventory', 'network_matrix', 'role_tokens', 'readme', 'checker', 'decision',
                'relies_on_decisions', 'statuses', 'acceptance', 'lanes', 'shared_object',
                'placement', 'runner_config', 'registration', 'gitea', 'reach', 'endpoint',
                'proxy', 'workflow', 'matrix_edits', 'owner_acts', 'checks', 'sources', 'notes'}
POLICY_KEYS = {'schema', 'plan_leaf', 'title', 'as_of', 'baseline_commit', 'profile', 'inventory',
               'role_tokens', 'readme', 'checker', 'decision', 'relies_on_decisions',
               'task_tokens', 'ceilings', 'secret_rules', 'credential_lanes', 'revocation',
               'source_archive', 'gitea_facts', 'disclosures', 'sources', 'notes'}

CODES = ('SCHEMA', 'STATUS_INVALID', 'DANGLING_REF', 'DECISION_UNLINKED', 'MACHINE_PATH',
         'README_STALE', 'CHECKS_STALE', 'LANE_PRIVILEGED', 'LANE_JOB_CREDENTIALS',
         'LANE_RUNNER_CREDENTIALS', 'LANE_HOLDS_MISMATCH', 'LANE_MAP_INCOMPLETE',
         'LANE_MAP_MISMATCH', 'JOB_REACH', 'TOKEN_ROW', 'RUNNER_RULE_MISSING', 'RUNNER_RULE_WEAK',
         'RUNNER_CONFIG', 'WORKFLOW_MISSING', 'WORKFLOW_SYNTAX', 'WORKFLOW_SCHEMA',
         'WORKFLOW_TRIGGER', 'WORKFLOW_PERMISSIONS', 'WORKFLOW_USES', 'WORKFLOW_SECRETS',
         'WORKFLOW_RUNS_ON', 'WORKFLOW_CONTAINER', 'WORKFLOW_INTERPOLATION',
         'WORKFLOW_FIRST_STEPS', 'WORKFLOW_ALLOWLIST', 'GITEA_ACTIONS_SCOPE', 'GITEA_PUBLIC_REPO',
         'GITEA_PROTECTION', 'GITEA_TOKEN_MODE', 'GITEA_CEILING', 'GITEA_CROSS_REPO',
         'GITEA_SECRETS', 'PROXY_ALLOWLIST', 'REGISTRATION_RESET', 'REGISTRATION_INPUT',
         'RUNNER_ENVIRONMENT', 'OWNER_ACT',
         'FORWARD_OWNER_ACT', 'FACT_UNSUPPORTED', 'FACT_ARCHIVE', 'REVOCATION_MISMATCH')
# Codes the inventory checker's link helpers emit, reported under ci-refs.
LINK_CODES = ('LINK_INVALID', 'LINK_MISSING', 'ANCHOR_MISSING')

GENERATED_BEGIN = '<!-- BEGIN GENERATED: python -I -B tools/check_ci_policy.py --render -->'
GENERATED_END = '<!-- END GENERATED -->'


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) else ''


def _in(key, table):
    return isinstance(key, str) and key in table


def _dicts(value):
    return [v for v in _list(value) if isinstance(v, dict)]


def _strs(value):
    return [v for v in _list(value) if isinstance(v, str)]


def _same(value, expected):
    """Equality that does not take False for 0 or 1 for True."""
    return type(value) is type(expected) and value == expected


# -- a strict YAML subset ------------------------------------------------------------------

class YamlSubsetError(ValueError):
    def __init__(self, line, message):
        super().__init__(f'line {line}: {message}')
        self.line = line


_KEY = re.compile(r'^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?: (.*))?$')


class _YamlSubset:
    """Block mappings and sequences, plain and quoted scalars, ``{}``, ``[]`` and literal
    blocks (``|``, ``|-``); full-line comments. Everything else (anchors, aliases, tags, flow
    collections, folded blocks, trailing comments, tabs, duplicate keys, documents) is an
    error: the checker reads only what it can read exactly."""

    def __init__(self, text):
        self.lines = [line.rstrip('\r') for line in text.split('\n')]
        self.i = 0

    def fail(self, message, line=None):
        raise YamlSubsetError(self.i + 1 if line is None else line, message)

    def peek(self):
        while self.i < len(self.lines):
            line = self.lines[self.i]
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                lead = line[:len(line) - len(line.lstrip(' \t'))]
                if '\t' in lead:
                    self.fail('a tab in the indentation')
                if stripped in ('---', '...'):
                    self.fail('document markers are not supported')
                indent = len(line) - len(line.lstrip(' '))
                return indent, line[indent:].rstrip(' ')
            self.i += 1
        return None

    def document(self):
        first = self.peek()
        if first is None:
            self.fail('an empty document')
        if first[0] != 0:
            self.fail('the document must start at column 0')
        value = self.block(0)
        if self.peek() is not None:
            self.fail('unexpected content after the document')
        return value

    def block(self, indent):
        _, content = self.peek()
        if content == '-' or content.startswith('- '):
            return self.sequence(indent)
        return self.mapping(indent)

    def mapping(self, indent):
        out = {}
        while True:
            head = self.peek()
            if head is None or head[0] < indent:
                return out
            if head[0] > indent:
                self.fail('unexpected indentation')
            content = head[1]
            if content == '-' or content.startswith('- '):
                self.fail('a sequence item where a key was expected')
            match = _KEY.match(content)
            if not match:
                self.fail(f'not a supported key: {content[:40]!r}')
            key, rest = match.group(1), match.group(2)
            if key in out:
                self.fail(f'duplicate key {key!r}')
            line = self.i + 1
            self.i += 1
            out[key] = self.value(rest, indent, line)

    def value(self, rest, indent, line):
        rest = (rest or '').strip(' ')
        if not rest:
            head = self.peek()
            if head is not None and head[0] > indent:
                return self.block(head[0])
            return None
        if rest in ('|', '|-'):
            return self.literal(indent, keep=rest == '|')
        return self.scalar(rest, line)

    def sequence(self, indent):
        out = []
        while True:
            head = self.peek()
            if head is None or head[0] < indent:
                return out
            if head[0] > indent:
                self.fail('unexpected indentation')
            content = head[1]
            if not (content == '-' or content.startswith('- ')):
                self.fail('a key where a sequence item was expected')
            line = self.i + 1
            item = content[1:].lstrip(' ')
            if not item:
                self.i += 1
                nxt = self.peek()
                out.append(self.block(nxt[0]) if nxt is not None and nxt[0] > indent else None)
            elif _KEY.match(item):
                column = indent + len(content) - len(item)
                self.lines[self.i] = ' ' * column + item
                out.append(self.mapping(column))
            else:
                self.i += 1
                out.append(self.scalar(item, line))

    def literal(self, indent, keep):
        block, block_indent = [], None
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip():
                block.append('')
                self.i += 1
                continue
            if '\t' in line[:len(line) - len(line.lstrip(' \t'))]:
                self.fail('a tab in the indentation')
            current = len(line) - len(line.lstrip(' '))
            if current <= indent:
                break
            if block_indent is None:
                block_indent = current
            elif current < block_indent:
                self.fail('a literal block line left of its indentation')
            block.append(line[block_indent:])
            self.i += 1
        while block and not block[-1]:
            block.pop()
        text = '\n'.join(block)
        return text + '\n' if keep and text else text

    def scalar(self, text, line):
        if text == '{}':
            return {}
        if text == '[]':
            return []
        if text.startswith('"'):
            if len(text) < 2 or not text.endswith('"'):
                self.fail('an unterminated double-quoted scalar', line)
            try:
                return json.loads(text)
            except ValueError:
                self.fail('an unsupported double-quoted scalar', line)
        if text.startswith("'"):
            inner = text[1:-1]
            if len(text) < 2 or not text.endswith("'") or "'" in inner.replace("''", ''):
                self.fail('an unsupported single-quoted scalar', line)
            return inner.replace("''", "'")
        if text[0] in '&*!|>%@`{}[],?:#' or text.startswith('- '):
            self.fail(f'an unsupported scalar: {text[:40]!r}', line)
        if ': ' in text or ' #' in text or text.endswith(':'):
            self.fail(f'an ambiguous plain scalar (": " or " #"): {text[:40]!r}', line)
        return text


def parse_yaml_subset(text):
    """Parse TEXT in the strict subset; raise YamlSubsetError on anything else."""
    if not isinstance(text, str):
        raise YamlSubsetError(0, 'not text')
    return _YamlSubset(text).document()


# -- the checker ---------------------------------------------------------------------------

class Checker(csi.Checker):
    """Reuses the inventory checker's link, status helpers and machine-path search."""

    def __init__(self, profile, policy, inputs, readme_text=None, workflows=None, profiles=None):
        super().__init__(inputs.inventory, inputs.root, readme_text, inputs.files)
        self.profile = profile
        self.policy = policy
        self.inputs = inputs
        self.workflows = inputs.workflows if workflows is None else workflows
        self.variants = inputs.profiles if profiles is None else profiles

    # -- helpers -----------------------------------------------------------------

    def keys(self, where, entry, allowed):
        for key in entry:
            if key not in allowed:
                self.add('SCHEMA', where, f'unknown key {key!r}')

    def leaf_ok(self, value):
        leaves = [value] if isinstance(value, str) else value
        return isinstance(leaves, list) and leaves and all(_in(v, self.plan) for v in leaves)

    def statement(self, where, entry):
        """Every statement carries a status from the closed set and a verify_at plan leaf; an
        observed one also its evidence."""
        if not isinstance(entry, dict):
            self.add('SCHEMA', where, 'must be an object')
            return
        if entry.get('status') not in STATUSES:
            self.add('STATUS_INVALID', where, f"status {entry.get('status')!r} is not one of "
                     f'{STATUSES}')
        if not self.leaf_ok(entry.get('verify_at')):
            self.add('STATUS_INVALID', where, f"verify_at {entry.get('verify_at')!r} is not a "
                     'plan leaf or a list of them')
        if entry.get('status') == 'observed' and not self.check_links(where, entry, 'evidence'):
            self.add('STATUS_INVALID', where, 'observed needs at least one evidence link')
        act = entry.get('owner_act')
        if act is not None and not _in(act, self.acts):
            self.add('DANGLING_REF', where, f'owner_act {act!r} is not an Owner act of the profile')

    def resolve(self, where, value, table, what):
        if not _in(value, table):
            self.add('DANGLING_REF', where, f'{what} {value!r} does not exist')
            return False
        return True

    # -- the checks --------------------------------------------------------------

    def run(self):
        prof, pol = self.profile, self.policy
        if not isinstance(prof, dict) or not isinstance(pol, dict):
            self.add('SCHEMA', 'policy', 'the profile and the token policy must be JSON objects')
            return self.problems
        if prof.get('schema') != PROFILE_SCHEMA:
            self.add('SCHEMA', 'profile.schema', f'expected {PROFILE_SCHEMA!r}')
        if pol.get('schema') != POLICY_SCHEMA:
            self.add('SCHEMA', 'policy.schema', f'expected {POLICY_SCHEMA!r}')
        self.keys('profile', prof, PROFILE_KEYS)
        self.keys('policy', pol, POLICY_KEYS)
        self.check_machine_paths(prof, 'profile')
        self.check_machine_paths(pol, 'policy')

        self.plan = self.plan_ids() or set()
        self.domains = self.index('trust_domains')
        self.principals = self.index('principals')
        self.credentials = self.index('credentials')
        self.assets = self.index('assets')
        self.findings = self.index('findings')
        self.edges = {e.get('id') for e in _dicts(_dict(self.inputs.matrix).get('edges'))
                      + _dicts(_dict(self.inputs.matrix).get('external_edges'))}
        self.roles = {r.get('id'): r for r in _dicts(_dict(self.inputs.role_tokens).get('roles'))
                      if isinstance(r.get('id'), str)}
        self.acts = {a.get('id'): a for a in _dicts(prof.get('owner_acts'))
                     if isinstance(a.get('id'), str)}

        for name, doc in (('profile', prof), ('policy', pol)):
            if not self.check_links(name, doc, 'sources'):
                self.add('STATUS_INVALID', f'{name}.sources', 'needs at least one source link')
            for key in ('token_policy', 'profile', 'inventory', 'network_matrix', 'role_tokens',
                        'readme', 'checker'):
                if key in doc:
                    self.check_link(f'{name}.{key}', doc.get(key))
            self.check_decision(name, doc)

        self.check_owner_acts()
        self.check_lanes()
        self.check_lane_map()
        self.check_reach()
        self.check_task_tokens()
        self.check_placement()
        self.check_runner_config()
        self.check_variants()
        self.check_registration()
        self.check_gitea()
        self.check_ceilings()
        self.check_secret_rules()
        self.check_endpoint_and_proxy()
        self.check_workflows()
        self.check_matrix_edits()
        self.check_facts()
        self.check_revocation()
        self.check_disclosures()
        self.check_checks()
        self.check_ci_readme()
        return self.problems

    def check_decision(self, name, doc):
        decision = doc.get('decision')
        where = f'{name}.decision'
        if not isinstance(decision, dict) or not DECISION_ID.match(_str(decision.get('id'))):
            self.add('SCHEMA', where, 'decision needs {id: NNNN, record, note}')
            return
        ident = decision['id']
        existing = self.inputs.decisions.get(ident)
        record = decision.get('record')
        if record is None:
            if not _str(decision.get('note')).strip():
                self.add('SCHEMA', where, 'an unlinked decision needs a note')
            if existing:
                self.add('DECISION_UNLINKED', where, f'decisions/{existing} exists: link it as '
                         'the record')
        elif not isinstance(record, str) or not record.startswith(f'decisions/{ident}-'):
            self.add('DANGLING_REF', where, f'record {record!r} is not decisions/{ident}-*.md')
        else:
            self.check_link(where, record)
        relies = doc.get('relies_on_decisions')
        if not isinstance(relies, list):
            self.add('SCHEMA', f'{name}.relies_on_decisions', 'must be a list of decision ids')
            relies = []
        for ident in relies:
            if not _in(ident, self.inputs.decisions):
                self.add('DANGLING_REF', f'{name}.relies_on_decisions',
                         f'decision {ident!r} has no record under decisions/')

    def check_owner_acts(self):
        acts = _list(self.profile.get('owner_acts'))
        if not acts:
            self.add('SCHEMA', 'owner_acts', 'must be a non-empty list')
        seen = set()
        for n, act in enumerate(acts):
            where = f'owner_acts[{n}]'
            if not isinstance(act, dict) or not isinstance(act.get('id'), str):
                self.add('SCHEMA', where, 'an Owner act needs an id')
                continue
            where = f"owner_acts.{act['id']}"
            if act['id'] in seen:
                self.add('SCHEMA', where, 'defined twice')
            seen.add(act['id'])
            self.keys(where, act, {'id', 'act', 'class', 'requested_at', 'status', 'approval',
                                   'notes'})
            if not _str(act.get('act')).strip() or not _str(act.get('class')).strip():
                self.add('SCHEMA', where, 'act and class are required')
            if not _in(act.get('requested_at'), self.plan):
                self.add('OWNER_ACT', where, f"requested_at {act.get('requested_at')!r} is not a "
                         'plan leaf: every Owner act names the leaf that requests it')
            if act.get('status') not in ACT_STATUSES:
                self.add('OWNER_ACT', where, f"status {act.get('status')!r} is not one of "
                         f'{ACT_STATUSES}')
            if act.get('status') == 'observed':
                self.check_approval(where, act.get('approval'))

    def check_approval(self, where, approval):
        if not isinstance(approval, dict) or approval.get('link') != BOOTSTRAP_LOG or \
                len(_str(approval.get('quote')).strip()) < 12:
            self.add('OWNER_ACT', where, f'an observed Owner act cites its approval: '
                     f'{{link: {BOOTSTRAP_LOG}, quote: <the approval, verbatim>}}')
            return
        text = self.read_text(BOOTSTRAP_LOG)
        if text is None or approval['quote'] not in text:
            self.add('OWNER_ACT', where, f'the quoted approval is not in {BOOTSTRAP_LOG}')

    def lane_map(self):
        out = {}
        for row in _dicts(self.policy.get('credential_lanes')):
            if isinstance(row.get('credential'), str) and isinstance(row.get('lane'), str):
                out.setdefault(row['lane'], set()).add(row['credential'])
        return out

    def check_lanes(self):
        lanes = _list(self.profile.get('lanes'))
        ids = [_dict(lane).get('id') for lane in lanes]
        if sorted(i for i in ids if isinstance(i, str)) != sorted(PROFILE_LANES) or \
                len(ids) != len(PROFILE_LANES):
            self.add('SCHEMA', 'lanes', f'must define exactly {list(PROFILE_LANES)}')
        mapped = self.lane_map()
        reach_ids = {r.get('id') for r in _dicts(self.profile.get('reach'))}
        for n, lane in enumerate(lanes):
            if not isinstance(lane, dict):
                self.add('SCHEMA', f'lanes[{n}]', 'must be an object')
                continue
            lid = lane.get('id')
            where = f'lanes.{lid}'
            self.keys(where, lane, {'id', 'name', 'domains', 'executes', 'holds', 'reaches',
                                    'produces', 'status', 'verify_at', 'notes'})
            self.statement(where, lane)
            domains = lane.get('domains')
            if not isinstance(domains, list) or not domains:
                self.add('SCHEMA', where, 'domains must be a non-empty list')
            for d in _list(domains):
                self.resolve(where, d, self.domains, 'trust domain')
            reaches = lane.get('reaches')
            if not isinstance(reaches, list):
                self.add('SCHEMA', where, 'reaches must be a list of reach ids')
                reaches = []
            for r in reaches:
                self.resolve(where, r, reach_ids, 'reach')
            if lid == 'validation-job' and reaches:
                self.add('JOB_REACH', where, f'the validation job reaches nothing; it lists {reaches}')
            if lid in ('validation-job', 'validation-runner-host'):
                holds = lane.get('holds')
                if not isinstance(holds, list) or not all(isinstance(h, str) for h in holds):
                    self.add('SCHEMA', where, 'holds must be a list of credential ids')
                    holds = []
                for cid in holds:
                    if self.resolve(where, cid, self.credentials, 'credential') and \
                            self.credentials[cid].get('authority') in csi.PRIVILEGED_AUTHORITIES:
                        self.add('LANE_PRIVILEGED', where, f'{cid} is a credential of '
                                 f"{self.credentials[cid].get('authority')} authority")
                if set(holds) != mapped.get(lid, set()):
                    self.add('LANE_HOLDS_MISMATCH', where, f'holds {sorted(holds)}, but the token '
                             f'policy maps {sorted(mapped.get(lid, set()))} to it')

    def check_lane_map(self):
        rows = self.policy.get('credential_lanes')
        if not isinstance(rows, list) or not rows:
            self.add('SCHEMA', 'credential_lanes', 'must be a non-empty list')
            rows = []
        seen = set()
        for n, row in enumerate(rows):
            where = f'credential_lanes[{n}]'
            if not isinstance(row, dict):
                self.add('SCHEMA', where, 'must be an object')
                continue
            cid, lane = row.get('credential'), row.get('lane')
            where = f'credential_lanes.{cid}'
            self.keys(where, row, {'credential', 'lane', 'reason'})
            if lane not in LANES:
                self.add('SCHEMA', where, f'lane {lane!r} is not one of {LANES}')
            if not _str(row.get('reason')).strip():
                self.add('SCHEMA', where, 'reason is required')
            if not self.resolve(where, cid, self.credentials, 'credential'):
                continue
            if cid in seen:
                self.add('SCHEMA', where, 'mapped twice')
            seen.add(cid)
            cred = self.credentials[cid]
            if _str(lane).startswith('validation-') and \
                    cred.get('authority') in csi.PRIVILEGED_AUTHORITIES:
                self.add('LANE_PRIVILEGED', where, f'a credential of {cred.get("authority")} '
                         f'authority in the {lane} lane')
            holder_domain = _dict(self.principals.get(cred.get('holder'))).get('domain')
            expected = LANE_OF_DOMAIN.get(holder_domain)
            if expected is not None and lane != expected:
                self.add('LANE_MAP_MISMATCH', where, f'held in {holder_domain}, so its lane is '
                         f'{expected}, not {lane}')
            if _str(lane).startswith('validation-') and expected != lane:
                self.add('LANE_MAP_MISMATCH', where, f'the {lane} lane holds only credentials held '
                         f'in its domain; {cid} is held in {holder_domain}')
        for cid in self.credentials:
            if cid not in seen:
                self.add('LANE_MAP_INCOMPLETE', f'credential_lanes.{cid}', 'every inventory '
                         'credential is assigned a lane')
        mapped = self.lane_map()
        if mapped.get('validation-job', set()) != set(JOB_CREDENTIALS):
            self.add('LANE_JOB_CREDENTIALS', 'credential_lanes', 'the validation job holds exactly '
                     f'{list(JOB_CREDENTIALS)}, not {sorted(mapped.get("validation-job", set()))}')
        if mapped.get('validation-runner-host', set()) != set(RUNNER_CREDENTIALS):
            self.add('LANE_RUNNER_CREDENTIALS', 'credential_lanes', 'the runner host holds exactly '
                     f'{list(RUNNER_CREDENTIALS)}, not '
                     f'{sorted(mapped.get("validation-runner-host", set()))}')

    def check_reach(self):
        rows = self.profile.get('reach')
        if not isinstance(rows, list) or not rows:
            self.add('SCHEMA', 'reach', 'must be a non-empty list')
            rows = []
        targets = {**self.domains, **self.assets, 'nothing': {}}
        for n, row in enumerate(rows):
            if not isinstance(row, dict):
                self.add('SCHEMA', f'reach[{n}]', 'must be an object')
                continue
            where = f"reach.{row.get('id')}"
            self.keys(where, row, {'id', 'from', 'to', 'kind', 'class', 'path', 'credentials',
                                   'owner_act', 'basis', 'status', 'verify_at', 'notes'})
            self.statement(where, row)
            self.resolve(where, row.get('from'), self.domains, 'trust domain')
            self.resolve(where, row.get('to'), targets, 'target')
            kind = row.get('kind')
            if kind not in REACH_KINDS:
                self.add('SCHEMA', where, f'kind {kind!r} is not one of {REACH_KINDS}')
            creds = row.get('credentials')
            if not isinstance(creds, list):
                self.add('SCHEMA', where, 'credentials must be a list')
                creds = []
            for cid in creds:
                self.resolve(where, cid, self.credentials, 'credential')
            if kind in ('forward', 'listener') and not _in(row.get('owner_act'), self.acts):
                self.add('FORWARD_OWNER_ACT', where, f'a {kind} is an Owner act: name it')
            if row.get('from') == 'td-untrusted-ci' and (kind != 'none' or creds):
                self.add('JOB_REACH', where, 'the validation job has no path to anything (decision '
                         '0013, point 7)')

    def check_task_tokens(self):
        rows = self.policy.get('task_tokens')
        if not isinstance(rows, list):
            self.add('SCHEMA', 'task_tokens', 'must be a list')
            rows = []
        names = set()
        for n, row in enumerate(rows):
            if not isinstance(row, dict):
                self.add('SCHEMA', f'task_tokens[{n}]', 'must be an object')
                continue
            cid = row.get('credential')
            where = f'task_tokens.{cid}'
            self.statement(where, row)
            if isinstance(cid, str):
                names.add(cid)
            cred = self.credentials.get(cid) if isinstance(cid, str) else None
            if cred is None:
                self.add('DANGLING_REF', where, f'credential {cid!r} does not exist')
            elif cred.get('holder') != 'ci-job' or row.get('issuer') != cred.get('issuer') or \
                    row.get('holder') != cred.get('holder') or \
                    row.get('manager') != cred.get('manager'):
                self.add('TOKEN_ROW', where, 'issuer, holder and manager must equal the '
                         'inventory\'s, and the holder is ci-job')
            if row.get('reach') != 'none' or row.get('relied_on') is not False:
                self.add('JOB_REACH', where, 'a task token reaches nothing (reach: none) and is '
                         'never relied on (relied_on: false)')
            perm = row.get('effective_permission')
            if not isinstance(perm, dict) or not perm:
                self.add('TOKEN_ROW', where, 'effective_permission must be a non-empty object')
            elif cid == 'cred-ci-job-token' and (
                    perm.get('governance_repository') != 'none' or
                    perm.get('other_private_repositories') != 'none'):
                self.add('TOKEN_ROW', where, 'the job token\'s effective permission is none on the '
                         'governance repository and on every other private repository')
        if names != set(JOB_CREDENTIALS):
            self.add('TOKEN_ROW', 'task_tokens', f'rows must exist for exactly {list(JOB_CREDENTIALS)}')

    def check_placement(self):
        placement = self.profile.get('placement')
        self.statement('placement', placement)
        placement = _dict(placement)
        for key in ('ceilings', 'lifetime_choice'):
            self.statement(f'placement.{key}', placement.get(key))
        choice = _dict(placement.get('lifetime_choice'))
        if 'mode' in choice:
            rows = {r['mode']: r for r in map(_dict, _list(placement.get('lifetimes')))
                    if isinstance(r.get('mode'), str)}
            row = rows.get(choice.get('mode')) if isinstance(choice.get('mode'), str) else None
            if row is None or row.get('runner') != choice.get('runner'):
                self.add('SCHEMA', 'placement.lifetime_choice', 'the chosen mode and runner are one '
                         f'of placement.lifetimes ({sorted(rows)})')

    def lifetime_mode(self):
        """The chosen lifetime's mode (shared or per-validation), or None."""
        mode = _dict(_dict(self.profile.get('placement')).get('lifetime_choice')).get('mode')
        return mode if isinstance(mode, str) else None

    def check_runner_config(self):
        cfg = self.profile.get('runner_config')
        self.statement('runner_config', cfg)
        cfg = _dict(cfg)
        rules = {}
        for n, rule in enumerate(_list(cfg.get('rules'))):
            if not isinstance(rule, dict) or not isinstance(rule.get('path'), str):
                self.add('SCHEMA', f'runner_config.rules[{n}]', 'a rule needs a path')
                continue
            self.statement(f"runner_config.rules.{rule['path']}", rule)
            rules[rule['path']] = rule
        for path, (kind, value) in REQUIRED_RULES.items():
            rule = rules.get(path)
            where = f'runner_config.rules.{path}'
            if rule is None:
                self.add('RUNNER_RULE_MISSING', where, f'the invariant {kind} is not declared')
            elif rule.get('rule') != kind or (kind == 'must_equal' and
                                               not _same(rule.get('value'), value)):
                self.add('RUNNER_RULE_WEAK', where, f'must be {kind}'
                         + (f' {value!r}' if kind == 'must_equal' else '') + ', the decided '
                         'invariant')
        label = _dict(cfg.get('label'))
        if label.get('name') != 'aieh-validation' or label.get('scheme') != 'docker':
            self.add('RUNNER_RULE_WEAK', 'runner_config.label', 'one label, aieh-validation, '
                     'backed by docker')
        options = cfg.get('options')
        self.statement('runner_config.options', options)
        declared = _strs(_dict(options).get('declared'))
        mount = _dict(options).get('exchange_mount')
        if not isinstance(mount, str) or mount not in declared or \
                not mount.startswith('--volume=') or not mount.endswith(':ro'):
            self.add('RUNNER_RULE_WEAK', 'runner_config.options', 'the exchange mount is declared, '
                     'read-only (--volume=...:ro)')
        for token in REQUIRED_OPTIONS:
            if token not in declared:
                self.add('RUNNER_RULE_WEAK', 'runner_config.options', f'{token} must be declared')
        for prefix in REQUIRED_OPTION_PREFIXES:
            if not any(t.startswith(prefix) for t in declared):
                self.add('RUNNER_RULE_WEAK', 'runner_config.options', f'{prefix}... must be declared')
        for token in declared:
            reason = forbidden_option(token, mount)
            if reason:
                self.add('RUNNER_RULE_WEAK', 'runner_config.options', f'{token}: {reason}')
        env = cfg.get('environment')
        self.statement('runner_config.environment', env)
        env = _dict(env)
        names = {n.upper() for n in _strs(env.get('forbidden_names'))}
        prefixes = {p.upper() for p in _strs(env.get('forbidden_prefixes'))}
        missing = [n for n in REQUIRED_ENV_NAMES if n not in names] + \
            [p for p in REQUIRED_ENV_PREFIXES if p not in prefixes]
        if missing or env.get('config_expansion') != 'refused' or not _str(env.get('service_key')):
            self.add('RUNNER_RULE_WEAK', 'runner_config.environment', 'the runner service\'s '
                     f'environment refuses {list(REQUIRED_ENV_NAMES)} and the prefixes '
                     f'{list(REQUIRED_ENV_PREFIXES)} (missing {missing}), names its service_key, and '
                     'config_expansion is refused')

    def env_problems(self, environment):
        """The forbidden names in one declared environment mapping (names without case)."""
        env = _dict(_dict(self.profile.get('runner_config')).get('environment'))
        names = {n.upper() for n in _strs(env.get('forbidden_names'))} | set(REQUIRED_ENV_NAMES)
        prefixes = tuple({p.upper() for p in _strs(env.get('forbidden_prefixes'))}
                         | set(REQUIRED_ENV_PREFIXES))
        if not isinstance(environment, dict):
            return ['the environment must be a mapping of names to values']
        return [f'{name!r} must not be set' for name in sorted(map(str, environment))
                if name.upper() in names or name.upper().startswith(prefixes)]

    def check_variants(self):
        cfg = _dict(self.profile.get('runner_config'))
        key = _str(cfg.get('profile_key'))
        if not key:
            self.add('SCHEMA', 'runner_config.profile_key', 'names where a profile variant '
                     'declares its config.yaml')
            return
        options = _dict(cfg.get('options'))
        declared = _strs(options.get('declared'))
        service_key = _str(_dict(cfg.get('environment')).get('service_key'))
        register_key = _str(_dict(_dict(self.profile.get('registration')).get('token_input'))
                            .get('register_key'))
        for name, variant in sorted(self.variants.items()):
            config = _get(variant, key) if isinstance(variant, dict) else None
            if config is None:
                continue
            for message in runner_config_violations(config, declared, options.get('exchange_mount')):
                self.add('RUNNER_CONFIG', f'profiles/{name}:{key}', message)
            for path in expansions(config):
                self.add('RUNNER_CONFIG', f'profiles/{name}:{key}', f'{path} holds $: the runner '
                         'expands ${NAME} from its environment when it loads the config')
            where = f'profiles/{name}:{service_key}'
            service = _get(variant, service_key) if service_key else None
            if not isinstance(service, dict):
                self.add('RUNNER_ENVIRONMENT', where, 'a variant declares its runner service '
                         '(environment and argv)')
            else:
                for message in self.env_problems(service.get('environment')):
                    self.add('RUNNER_ENVIRONMENT', where, f'environment: {message}')
                argv = service.get('argv')
                if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
                    self.add('RUNNER_ENVIRONMENT', where, 'argv must be a list of strings')
                else:
                    if 'daemon' not in argv or flag_value(argv, '--config') in (None, ''):
                        self.add('RUNNER_ENVIRONMENT', where, 'argv runs the daemon with --config '
                                 '<the declared config.yaml>')
                    if has_flag(argv, '--labels'):
                        self.add('RUNNER_ENVIRONMENT', where, 'argv: --labels overrides the '
                                 'registered labels; the labels come from the config only')
            self.check_register(name, variant, register_key)

    def check_register(self, name, variant, register_key):
        where = f'profiles/{name}:{register_key}'
        register = _get(variant, register_key) if register_key else None
        if not isinstance(register, dict):
            self.add('REGISTRATION_INPUT', where, 'a variant declares its register call (argv)')
            return
        for message in self.env_problems(register.get('environment', {})):
            self.add('REGISTRATION_INPUT', where, f'environment: {message}')
        argv = register.get('argv')
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            self.add('REGISTRATION_INPUT', where, 'argv must be a list of strings')
            return
        token_input = _dict(_dict(self.profile.get('registration')).get('token_input'))
        prefix = _str(token_input.get('path_prefix')) or TOKEN_PATH_PREFIX
        token_file = flag_value(argv, TOKEN_FLAG)
        if 'register' not in argv or '--no-interactive' not in argv:
            self.add('REGISTRATION_INPUT', where, 'argv is a non-interactive register call')
        if not isinstance(token_file, str) or not token_file.startswith(prefix) or \
                '..' in token_file.split('/'):
            self.add('REGISTRATION_INPUT', where, f'the token enters by {TOKEN_FLAG} <a file under '
                     f'{prefix}>')
        if has_flag(argv, '--token'):
            self.add('REGISTRATION_INPUT', where, 'the token never enters by --token (the command '
                     'line)')
        if flag_value(argv, '--config') in (None, ''):
            self.add('REGISTRATION_INPUT', where, 'register reads the declared config (--config): '
                     'without it the runner registers its default labels')
        if has_flag(argv, '--labels'):
            self.add('REGISTRATION_INPUT', where, 'the labels come from the config only (no '
                     '--labels)')
        instance = _dict(self.profile.get('endpoint')).get('runner_instance_url')
        if flag_value(argv, '--instance') != instance:
            self.add('REGISTRATION_INPUT', where, f'--instance is the ci-control endpoint '
                     f'{instance!r}')
        mode = self.lifetime_mode()
        ephemeral = has_flag(argv, '--ephemeral')
        if mode is None or ephemeral != (mode == 'per-validation'):
            self.add('REGISTRATION_INPUT', where, f'--ephemeral is given exactly when the chosen '
                     f'lifetime is per-validation (chosen: {mode!r})')

    def check_registration(self):
        reg = self.profile.get('registration')
        self.statement('registration', reg)
        reg = _dict(reg)
        steps = [_str(_dict(s).get('step')) for s in _list(reg.get('procedure'))]
        reset_after = 'register' in steps and 'reset' in steps[steps.index('register') + 1:]
        if _dict(reg.get('fallback')).get('in_force') not in (None, False):
            self.add('REGISTRATION_RESET', 'registration.fallback', 'a registration token standing '
                     'between provisionings is never in force for a live runner (the Owner\'s '
                     'direction of 2026-11-10, decision 0016)')
        if not reset_after:
            self.add('REGISTRATION_RESET', 'registration.procedure', 'the registration token is '
                     'reset after the register step, so the delivered value is dead before any job '
                     'runs')
        if 'register' in steps and 'reset' not in steps[:steps.index('register')]:
            self.add('REGISTRATION_RESET', 'registration.procedure', 'a fresh token is made by a '
                     'reset before it is read and delivered')
        gate = reg.get('live_gate')
        self.statement('registration.live_gate', gate)
        gate = _dict(gate)
        verify_at = gate.get('verify_at')
        if gate.get('on_unverified') != 'block' or not _strs(gate.get('alternatives')) or \
                'Q-02.2.2' not in ([verify_at] if isinstance(verify_at, str) else _strs(verify_at)):
            self.add('REGISTRATION_RESET', 'registration.live_gate', 'a live runner waits on the '
                     'live proof that the reset invalidates the delivered value (verify_at '
                     'Q-02.2.2); unverified, it blocks (on_unverified: block) and names its '
                     'alternatives')
        token_input = reg.get('token_input')
        self.statement('registration.token_input', token_input)
        token_input = _dict(token_input)
        refused = _strs(token_input.get('refused'))
        if token_input.get('flag') != TOKEN_FLAG or token_input.get('path_prefix') != \
                TOKEN_PATH_PREFIX or any(r not in refused for r in TOKEN_REFUSED) or \
                not _str(token_input.get('register_key')):
            self.add('REGISTRATION_INPUT', 'registration.token_input', f'the registration token '
                     f'enters by {TOKEN_FLAG} from a file under {TOKEN_PATH_PREFIX} only, '
                     f'{list(TOKEN_REFUSED)} are refused, and register_key names where a variant '
                     'declares its register call')

    def governance(self):
        repos = [r for r in _dicts(_dict(self.profile.get('gitea')).get('repositories'))
                 if r.get('role') == 'governance']
        return repos[0] if len(repos) == 1 else None

    def check_gitea(self):
        gitea = _dict(self.profile.get('gitea'))
        instance = gitea.get('instance')
        self.statement('gitea.instance', instance)
        instance = _dict(instance)
        if instance.get('default_actions_url') != 'self':
            self.add('GITEA_ACTIONS_SCOPE', 'gitea.instance', 'DEFAULT_ACTIONS_URL is self, so a '
                     'stray uses: fails locally')
        today = _dict(instance.get('today'))
        if today:
            self.check_links('gitea.instance.today', today, 'evidence')
        repos = gitea.get('repositories')
        if not isinstance(repos, list):
            self.add('SCHEMA', 'gitea.repositories', 'must be a list')
            repos = []
        if self.governance() is None:
            self.add('GITEA_ACTIONS_SCOPE', 'gitea.repositories', 'exactly one governance '
                     'repository is declared')
        for n, repo in enumerate(repos):
            if not isinstance(repo, dict):
                self.add('SCHEMA', f'gitea.repositories[{n}]', 'must be an object')
                continue
            where = f"gitea.repositories.{repo.get('repository')}"
            self.statement(where, repo)
            if repo.get('actions_enabled') is not False and repo.get('role') != 'governance':
                self.add('GITEA_ACTIONS_SCOPE', where, 'Actions is enabled on the governance '
                         'repository only')
            if repo.get('private') is not True:
                self.add('GITEA_PUBLIC_REPO', where, 'every repository on the instance is private')
            if repo.get('role') == 'governance':
                if repo.get('actions_enabled') is not True:
                    self.add('GITEA_ACTIONS_SCOPE', where, 'the governance repository has Actions')
                prot = _dict(repo.get('protections'))
                missing = [p for p in PROTECTIONS if prot.get(p) is not True]
                if missing:
                    self.add('GITEA_PROTECTION', where, f'the governance protection needs {missing}')
        other = gitea.get('every_other_repository')
        self.statement('gitea.every_other_repository', other)
        other = _dict(other)
        if other.get('actions_enabled') is not False:
            self.add('GITEA_ACTIONS_SCOPE', 'gitea.every_other_repository', 'Actions is disabled on '
                     'every repository that receives proposals')
        if other.get('private') is not True:
            self.add('GITEA_PUBLIC_REPO', 'gitea.every_other_repository', 'every repository is '
                     'private')
        if gitea.get('public_repositories') != []:
            self.add('GITEA_PUBLIC_REPO', 'gitea.public_repositories', 'no public repository exists '
                     'on the instance (G4: every job token reads them)')
        secrets = gitea.get('secrets')
        self.statement('gitea.secrets', secrets)
        for key in SECRET_SETS:
            if _dict(secrets).get(key) != []:
                self.add('GITEA_SECRETS', f'gitea.secrets.{key}', 'no Actions secret or variable '
                         'exists anywhere (G5)')
        self.statement('gitea.live_check', gitea.get('live_check'))
        reg = _dict(self.profile.get('registration'))
        gov = self.governance()
        if gov is not None and reg.get('scope') != gov.get('repository'):
            self.add('SCHEMA', 'registration.scope', 'the registration scope is the governance '
                     'repository')

    def check_ceilings(self):
        ceilings = _dict(self.policy.get('ceilings'))
        if ceilings.get('units') != list(UNITS):
            self.add('SCHEMA', 'ceilings.units', f'must be exactly {list(UNITS)}')
        gov = _str(_dict(self.governance()).get('repository'))
        owners = {}
        for n, row in enumerate(_list(ceilings.get('owners'))):
            where = f"ceilings.owners.{_dict(row).get('owner')}"
            self.statement(where, row)
            row = _dict(row)
            owners[row.get('owner')] = row
            self.ceiling(where, row)
            if row.get('allowed_cross_repo_ids') != []:
                self.add('GITEA_CROSS_REPO', where, 'no AllowedCrossRepoIDs')
        repos = {}
        for n, row in enumerate(_list(ceilings.get('repositories'))):
            where = f"ceilings.repositories.{_dict(row).get('repository')}"
            self.statement(where, row)
            row = _dict(row)
            repos[row.get('repository')] = row
            self.ceiling(where, row)
            if row.get('override_owner_config') is not False:
                self.add('GITEA_CEILING', where, 'the owner\'s ceiling governs '
                         '(override_owner_config: false)')
            if row.get('collaborative_owner_ids') != []:
                self.add('GITEA_CROSS_REPO', where, 'no CollaborativeOwnerIDs')
        if gov and (gov.split('/')[0] not in owners or gov not in repos):
            self.add('GITEA_CEILING', 'ceilings', f'the governance owner and repository ({gov}) '
                     'each declare their ceiling')
        for key, field in (('every_owner', 'allowed_cross_repo_ids'),
                           ('every_repository', 'collaborative_owner_ids')):
            self.statement(f'ceilings.{key}', ceilings.get(key))
            if _dict(ceilings.get(key)).get(field) != []:
                self.add('GITEA_CROSS_REPO', f'ceilings.{key}', f'{field} is empty everywhere')
        wp = ceilings.get('workflow_permissions')
        self.statement('ceilings.workflow_permissions', wp)
        if _dict(wp).get('top_level') != '{}' or _dict(wp).get('job_level') != 'absent':
            self.add('GITEA_CEILING', 'ceilings.workflow_permissions', 'permissions: {} at the top '
                     'level and none at the job level')

    def ceiling(self, where, row):
        if row.get('token_permission_mode') != 'restricted':
            self.add('GITEA_TOKEN_MODE', where, 'the token permission mode is restricted')
        perms = row.get('max_token_permissions')
        if not isinstance(perms, dict) or sorted(perms) != sorted(UNITS) or \
                any(v != 'none' for v in perms.values()):
            self.add('GITEA_CEILING', where, f'the ceiling is none on every unit {list(UNITS)}')

    def check_secret_rules(self):
        rows = self.policy.get('secret_rules')
        if not isinstance(rows, list) or not rows:
            self.add('SCHEMA', 'secret_rules', 'must be a non-empty list')
            rows = []
        for n, row in enumerate(rows):
            self.statement(f"secret_rules.{_dict(row).get('id', n)}", row)
            if not _str(_dict(row).get('rule')).strip():
                self.add('SCHEMA', f'secret_rules[{n}]', 'rule is required')

    def check_endpoint_and_proxy(self):
        endpoint = self.profile.get('endpoint')
        self.statement('endpoint', endpoint)
        if not _in(_dict(endpoint).get('owner_act'), self.acts):
            self.add('FORWARD_OWNER_ACT', 'endpoint', 'the ci-control forward is an Owner act')
        if _dict(endpoint).get('class') != 'ci-control':
            self.add('SCHEMA', 'endpoint', 'the endpoint class is ci-control')
        proxy = self.profile.get('proxy')
        self.statement('proxy', proxy)
        proxy = _dict(proxy)
        if not _in(proxy.get('owner_act'), self.acts):
            self.add('FORWARD_OWNER_ACT', 'proxy', 'the proxy\'s host listener is an Owner act')
        allow = {}
        for row in _list(proxy.get('allow')):
            row = _dict(row)
            allow[(_str(row.get('method')), _str(row.get('path')))] = row.get('window')
        if allow != PROXY_ALLOW or len(_list(proxy.get('allow'))) != len(PROXY_ALLOW):
            self.add('PROXY_ALLOWLIST', 'proxy.allow', 'exactly the runner RPC: the ping service '
                     'and Register (provisioning window only), Declare, FetchTask, UpdateTask and '
                     'UpdateLog')
        deny = _strs(proxy.get('deny'))
        missing = [d for d in PROXY_DENY if d not in deny]
        if missing:
            self.add('PROXY_ALLOWLIST', 'proxy.deny', f'must name {missing}')

    def check_matrix_edits(self):
        for n, row in enumerate(_list(self.profile.get('matrix_edits'))):
            row = _dict(row)
            where = f"matrix_edits.{row.get('edge', n)}"
            self.resolve(where, row.get('edge'), self.edges, 'matrix edge')
            if not _in(row.get('at'), self.plan):
                self.add('DANGLING_REF', where, f"at {row.get('at')!r} is not a plan leaf")
        for n, row in enumerate(_list(self.profile.get('acceptance'))):
            for cid in _list(_dict(row).get('checks')):
                self.resolve(f'acceptance[{n}]', cid, self.check_ids(), 'check')

    def check_ids(self):
        return {c.get('id') for c in _dicts(self.profile.get('checks'))}

    def check_facts(self):
        facts = self.policy.get('gitea_facts')
        if not isinstance(facts, list) or not facts:
            self.add('SCHEMA', 'gitea_facts', 'must be a non-empty list')
            facts = []
        seen, sourced = set(), False
        for n, fact in enumerate(facts):
            if not isinstance(fact, dict) or not isinstance(fact.get('id'), str):
                self.add('SCHEMA', f'gitea_facts[{n}]', 'a fact needs an id')
                continue
            where = f"gitea_facts.{fact['id']}"
            if fact['id'] in seen:
                self.add('SCHEMA', where, 'defined twice')
            seen.add(fact['id'])
            self.keys(where, fact, {'id', 'fact', 'verified', 'source', 'verify_live_at',
                                    'verify_at', 'evidence', 'notes'})
            verified = fact.get('verified')
            if verified == 'source':
                sourced = True
                sources = fact.get('source')
                if not isinstance(sources, list) or not sources or not all(
                        isinstance(s, dict) and source_path_ok(s.get('path'))
                        and LINES.match(_str(s.get('lines'))) for s in sources):
                    self.add('FACT_UNSUPPORTED', where, 'verified at source needs [{path, lines}] '
                             'at the pin')
                if 'verify_live_at' in fact and not _in(fact.get('verify_live_at'), self.plan):
                    self.add('DANGLING_REF', where, 'verify_live_at is not a plan leaf')
            elif verified == 'live':
                if not self.check_links(where, fact, 'evidence'):
                    self.add('FACT_UNSUPPORTED', where, 'verified live needs evidence')
            elif verified is False:
                if not _in(fact.get('verify_at'), self.plan):
                    self.add('FACT_UNSUPPORTED', where, 'an unverified fact names the leaf that '
                             'verifies it (verify_at)')
            else:
                self.add('FACT_UNSUPPORTED', where, f'verified {verified!r} is not source, live or '
                         'false')
        if sourced:
            self.check_archive()

    def check_archive(self):
        archive = self.policy.get('source_archive')
        if not isinstance(archive, dict):
            self.add('FACT_ARCHIVE', 'source_archive', 'facts verified at source name the archive')
            return
        if archive.get('lock') != LOCK:
            self.add('FACT_ARCHIVE', 'source_archive', f'the archive is pinned by {LOCK}')
        pinned = [a for a in _dicts(_dict(self.inputs.lock).get('release_assets'))
                  if a.get('name') == archive.get('name')]
        if len(pinned) != 1 or pinned[0].get('sha256') != archive.get('sha256'):
            self.add('FACT_ARCHIVE', 'source_archive', f"{archive.get('name')!r} with sha256 "
                     f"{archive.get('sha256')!r} is not pinned in {LOCK}")
        if not self.check_links('source_archive', archive, 'evidence'):
            self.add('FACT_ARCHIVE', 'source_archive', 'the source check cites its evidence')

    def check_revocation(self):
        triggers = set(_dict(_dict(self.inputs.role_tokens).get('trigger_classes')))
        theirs = {}
        for role in self.roles.values():
            for row in _dicts(role.get('revocation')):
                if isinstance(row.get('credential'), str):
                    theirs[row['credential']] = row
        rows = {}
        for n, row in enumerate(_list(self.policy.get('revocation'))):
            row = _dict(row)
            cid = row.get('credential')
            where = f'revocation.{cid}'
            if not self.resolve(where, cid, self.credentials, 'credential'):
                continue
            rows[cid] = row
            mine = row.get('triggers')
            if not isinstance(mine, list) or not mine or any(not _in(t, triggers) for t in mine):
                self.add('SCHEMA', where, f'triggers must be a non-empty subset of {sorted(triggers)}')
                mine = []
            other = theirs.get(cid)
            if other is None:
                self.add('REVOCATION_MISMATCH', where, 'the role-token matrix has no revocation row '
                         'for it')
            elif other.get('revoker') != row.get('revoker') or \
                    other.get('rotation_owner') != row.get('rotation_owner') or \
                    set(_strs(other.get('triggers'))) != set(_strs(mine)):
                self.add('REVOCATION_MISMATCH', where, 'revoker, rotation owner and triggers must '
                         'equal the role-token matrix\'s row')
        for cid in REVOCATION_REQUIRED:
            if cid not in rows:
                self.add('REVOCATION_MISMATCH', f'revocation.{cid}', 'a revocation row is required')

    def check_disclosures(self):
        for n, row in enumerate(_list(self.policy.get('disclosures'))):
            row = _dict(row)
            where = f"disclosures.{row.get('id', n)}"
            if not _str(row.get('text')).strip():
                self.add('SCHEMA', where, 'text is required')
            for ref in _list(row.get('findings')):
                self.resolve(where, ref, self.findings, 'finding')

    def check_checks(self):
        named = set()
        for n, row in enumerate(_list(self.profile.get('checks'))):
            row = _dict(row)
            for code in _list(row.get('codes')):
                if isinstance(code, str):
                    named.add(code)
        codes = set(CODES) | set(LINK_CODES)
        if named != codes:
            self.add('CHECKS_STALE', 'checks', f'must name exactly the checker\'s codes: missing '
                     f'{sorted(codes - named)}, unknown {sorted(named - codes)}')

    # -- the workflows ---------------------------------------------------------------

    def check_workflows(self):
        wf = self.profile.get('workflow')
        self.statement('workflow', wf)
        wf = _dict(wf)
        source = wf.get('source_of_record')
        if not isinstance(source, str) or source not in self.workflows:
            self.add('WORKFLOW_MISSING', 'workflow.source_of_record', f'{source!r} is not a '
                     f"workflow under {wf.get('directory')!r}")
        for rel, text in sorted(self.workflows.items()):
            self.check_machine_paths(text, rel)
            try:
                doc = parse_yaml_subset(text)
            except YamlSubsetError as exc:
                self.add('WORKFLOW_SYNTAX', rel, f'{exc} (the checker reads a strict YAML subset)')
                continue
            self.check_workflow(rel, doc, wf)

    def check_workflow(self, rel, doc, wf):
        if not isinstance(doc, dict):
            self.add('WORKFLOW_SCHEMA', rel, 'a workflow is a mapping')
            return
        for key in doc:
            if key not in WORKFLOW_TOP_KEYS:
                self.add('WORKFLOW_SCHEMA', rel, f'unknown top-level key {key!r}')
        inputs = _strs(wf.get('inputs'))
        trigger = doc.get('on')
        given = _dict(_dict(_dict(trigger).get('workflow_dispatch')).get('inputs'))
        if not isinstance(trigger, dict) or list(trigger) != ['workflow_dispatch'] or \
                set(_dict(trigger.get('workflow_dispatch'))) != {'inputs'} or \
                sorted(given) != sorted(inputs) or not inputs:
            self.add('WORKFLOW_TRIGGER', rel, f'on: is exactly workflow_dispatch with the inputs '
                     f'{inputs}')
        if 'permissions' not in doc or not _same(doc.get('permissions'), {}):
            self.add('WORKFLOW_PERMISSIONS', rel, 'a top-level permissions: {} (none on every unit)')
        allowed_env = {}
        input_env = _dict(wf.get('input_env'))
        for name in inputs:
            if isinstance(input_env.get(name), str):
                allowed_env[input_env[name]] = '${{ inputs.%s }}' % name
        self.walk(rel, doc, (), allowed_env)
        jobs = doc.get('jobs')
        if not isinstance(jobs, dict) or not jobs:
            self.add('WORKFLOW_SCHEMA', rel, 'jobs must be a non-empty mapping')
            return
        for jid, job in jobs.items():
            self.check_job(f'{rel}:jobs.{jid}', job, wf, allowed_env)

    def walk(self, rel, value, path, allowed_env):
        """Every uses:, container:, services: and non-top-level permissions: anywhere; every
        secrets./vars. reference; every expression outside the job's three input variables."""
        if isinstance(value, dict):
            for key, item in value.items():
                here = path + (key,)
                where = f"{rel}:{'.'.join(map(str, here))}"
                if key == 'uses':
                    self.add('WORKFLOW_USES', where, 'no uses: anywhere: nothing is fetched at run time')
                if key in ('container', 'services'):
                    self.add('WORKFLOW_CONTAINER', where, f'no {key}: override')
                if key == 'permissions' and path:
                    self.add('WORKFLOW_PERMISSIONS', where, 'permissions: only at the top level')
                self.walk(rel, item, here, allowed_env)
        elif isinstance(value, list):
            for n, item in enumerate(value):
                self.walk(rel, item, path + (n,), allowed_env)
        elif isinstance(value, str):
            where = f"{rel}:{'.'.join(map(str, path))}"
            if SECRET_REF.search(value):
                self.add('WORKFLOW_SECRETS', where, 'no secrets. or vars. reference')
            if EXPRESSION.search(value):
                ok = len(path) == 4 and path[0] == 'jobs' and path[2] == 'env' and \
                    allowed_env.get(path[3]) == value
                if not ok:
                    self.add('WORKFLOW_INTERPOLATION', where, 'an expression is admitted only as '
                             'a job env value carrying one validated input')

    def check_job(self, where, job, wf, allowed_env):
        if not isinstance(job, dict):
            self.add('WORKFLOW_SCHEMA', where, 'a job is a mapping')
            return
        for key in job:
            if key not in JOB_KEYS and key not in ('container', 'services', 'permissions', 'uses'):
                self.add('WORKFLOW_SCHEMA', where, f'unsupported job key {key!r}')
        if not _same(job.get('runs-on'), _str(wf.get('runs_on'))) or not wf.get('runs_on'):
            self.add('WORKFLOW_RUNS_ON', where, f"runs-on is {wf.get('runs_on')!r} only")
        env = _dict(job.get('env'))
        for name, value in allowed_env.items():
            if env.get(name) != value:
                self.add('WORKFLOW_FIRST_STEPS', where, f'the job env carries {name}: {value}')
        steps = job.get('steps')
        if not isinstance(steps, list) or not steps:
            self.add('WORKFLOW_SCHEMA', where, 'steps must be a non-empty list')
            return
        for n, step in enumerate(steps):
            if not isinstance(step, dict):
                self.add('WORKFLOW_SCHEMA', f'{where}.steps[{n}]', 'a step is a mapping')
                continue
            for key in step:
                if key not in STEP_KEYS and key != 'uses':
                    self.add('WORKFLOW_SCHEMA', f'{where}.steps[{n}]', f'unsupported step key '
                             f'{key!r} (if: and continue-on-error: could skip or soften a step)')
            if not isinstance(step.get('run'), str) or not step.get('run').strip():
                self.add('WORKFLOW_SCHEMA', f'{where}.steps[{n}]', 'every step runs a command')
        first = _strs(wf.get('first_steps'))
        ids = [_dict(s).get('id') for s in steps[:len(first)]]
        if not first or ids != first:
            self.add('WORKFLOW_FIRST_STEPS', where, f'the first steps are {first}, in that order; '
                     f'found {ids}')
            return
        self.check_first_steps(where, [_dict(s) for s in steps[:len(first)]], wf, allowed_env)

    def check_first_steps(self, where, steps, wf, allowed_env):
        validate, verify, checkout = (_str(s.get('run')) for s in steps[:3])
        patterns = _dict(wf.get('input_patterns'))
        allow_env = _str(wf.get('allowlist_env'))
        needs = [p for p in patterns.values() if isinstance(p, str)] + \
            [f'${n}' for n in allowed_env] + ([f'${allow_env}'] if allow_env else [])
        missing = [n for n in needs if n not in validate]
        if len(patterns) != len(_strs(wf.get('inputs'))) or missing or not allow_env:
            self.add('WORKFLOW_FIRST_STEPS', where, f'the first step matches every input against its '
                     f'strict pattern and the allowlist; missing {missing}')
        bundle_env = _dict(wf.get('input_env')).get('bundle_sha256')
        sha_env = _dict(wf.get('input_env')).get('sha')
        if not all(n in verify for n in (f'${bundle_env}', 'sha256sum', 'bundle verify')):
            self.add('WORKFLOW_FIRST_STEPS', where, 'the second step checks the bundle\'s sha256 '
                     'against the input and runs git bundle verify')
        if not all(n in checkout for n in (f'${sha_env}', 'clone', 'rev-parse HEAD')):
            self.add('WORKFLOW_FIRST_STEPS', where, 'the third step clones the bundle, checks out '
                     'the SHA and asserts HEAD equals it')
        allowlist = _dict(steps[0].get('env')).get(allow_env)
        names = allowlist.split() if isinstance(allowlist, str) else None
        expected = _strs(_dict(wf).get('allowed_repositories'))
        if names is None or names != expected or \
                len(expected) != len(_list(wf.get('allowed_repositories'))):
            self.add('WORKFLOW_ALLOWLIST', where, f'the first step\'s {allow_env} is exactly the '
                     f'profile\'s allowlist {expected}')

    # -- the README ------------------------------------------------------------------

    def check_ci_readme(self):
        if self.readme is None:
            return
        block = generated_block(self.readme)
        if block is None:
            self.add('README_STALE', 'readme', 'the generated block is missing its markers')
        else:
            if csi.machine_path(block):
                self.add('MACHINE_PATH', 'readme', 'a machine-specific path must not be published')
            if block.strip() != render(self.profile, self.policy).strip():
                self.add('README_STALE', 'readme', 'the generated block differs from --render; '
                         're-render it from the profile and the token policy')


def source_path_ok(path):
    return isinstance(path, str) and path and not path.startswith(('/', '\\')) and \
        '..' not in path.split('/') and not csi.machine_path(path)


def forbidden_option(token, mount):
    """Why a container.options token weakens the job container, or None."""
    if token == mount and isinstance(mount, str) and mount.endswith(':ro'):
        return None
    if token == '--security-opt=no-new-privileges':
        return None
    name = token.split('=', 1)[0]
    if name in FORBIDDEN_OPTIONS or token.startswith('-v'):
        return 'a forbidden option (privilege, device, namespace, network, security or mount)'
    if name == '--user':
        user = token.split('=', 1)[1] if '=' in token else ''
        if user.split(':')[0] in ('', '0', 'root'):
            return 'the job runs as a non-root user'
    if name == '--cap-drop' and token != '--cap-drop=ALL':
        return 'every capability is dropped (--cap-drop=ALL)'
    return None


def _get(config, path):
    value = config
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def has_flag(argv, flag):
    """Whether ARGV gives FLAG, as '--flag' or '--flag=value'."""
    return any(a == flag or a.startswith(flag + '=') for a in argv)


def flag_value(argv, flag):
    """The value ARGV gives FLAG (the last one, as the command parser takes it): '' for a
    flag without a value, None when it is absent."""
    value = None
    for n, token in enumerate(argv):
        if token == flag:
            value = argv[n + 1] if n + 1 < len(argv) else ''
        elif token.startswith(flag + '='):
            value = token.split('=', 1)[1]
    return value


def expansions(value, path=''):
    """The paths of the string values (and keys) of a declared config that hold '$'."""
    out = []
    if isinstance(value, dict):
        for key, item in value.items():
            sub = f'{path}.{key}' if path else str(key)
            if '$' in str(key):
                out.append(sub)
            out.extend(expansions(item, sub))
    elif isinstance(value, list):
        for n, item in enumerate(value):
            out.extend(expansions(item, f'{path}[{n}]'))
    elif isinstance(value, str) and '$' in value:
        out.append(path or '<config>')
    return out


def runner_config_violations(config, declared, mount):
    """The violations of the decided invariants in one declared act_runner config (a JSON
    mirror of its config.yaml)."""
    out = []
    if not isinstance(config, dict):
        return ['the declared config is not a mapping']
    for path, (kind, expected) in REQUIRED_RULES.items():
        value = _get(config, path)
        if kind == 'must_equal' and not _same(value, expected):
            out.append(f'{path} must be {expected!r}, not {value!r}')
        elif kind == 'must_be_empty' and value not in (None, '', [], {}):
            out.append(f'{path} must be empty, not {value!r}')
        elif kind == 'must_be_set' and (value in (None, '', 0, [], {}) or isinstance(value, bool)):
            out.append(f'{path} must be set')
        elif kind == 'labels':
            if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str) \
                    or not LABEL.match(value[0]):
                out.append(f'{path} must be exactly one label aieh-validation:docker://<image>'
                           f'@sha256:<digest> (no host or lxc label), not {value!r}')
        elif kind == 'options':
            if value is None:
                value = ''
            if not isinstance(value, str):
                out.append(f'{path} must be a string of options')
                continue
            try:
                tokens = shlex.split(value)
            except ValueError as exc:
                out.append(f'{path} cannot be split: {exc}')
                continue
            for token in tokens:
                reason = forbidden_option(token, mount)
                if reason or token not in declared:
                    out.append(f'{path}: {token!r} is not a declared option'
                               + (f' ({reason})' if reason else ''))
            missing = [t for t in declared if t not in tokens]
            if missing:
                out.append(f'{path} lacks the declared options {missing}')
    return out


def generated_block(text):
    start = text.find(GENERATED_BEGIN)
    if start < 0:
        return None
    end = text.find(GENERATED_END, start)
    if end < 0:
        return None
    return text[start + len(GENERATED_BEGIN):end]


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _ids(values):
    values = [str(v) for v in _list(values)]
    return ', '.join(f'`{v}`' for v in values) if values else '-'


def _leaves(value):
    return ', '.join(str(v) for v in value) if isinstance(value, list) else str(value)


def render(profile, policy):
    """The README's generated block, rendered from the profile and the token policy."""
    profile, policy = _dict(profile), _dict(policy)
    out = ['', '### Lanes', '',
           '| Lane | Domains | Holds | Reaches | Status | Verify at |', '|---|---|---|---|---|---|']
    for lane in _dicts(profile.get('lanes')):
        holds = lane.get('holds')
        holds = _ids(holds) if isinstance(holds, list) else _cell(_str(holds))
        out.append(f"| `{lane.get('id')}` {_cell(_str(lane.get('name')))} | "
                   f"{_ids(lane.get('domains'))} | {holds} | {_ids(lane.get('reaches'))} | "
                   f"{lane.get('status')} | {_leaves(lane.get('verify_at'))} |")
    out += ['', '### Credential-to-lane map', '', '| Credential | Lane | Reason |', '|---|---|---|']
    for row in _dicts(policy.get('credential_lanes')):
        out.append(f"| `{row.get('credential')}` | {row.get('lane')} | "
                   f"{_cell(_str(row.get('reason')))} |")
    out += ['', '### Task tokens', '',
            '| Token | Effective permission | Reach | Relied on | Lifetime | Status |',
            '|---|---|---|---|---|---|']
    for row in _dicts(policy.get('task_tokens')):
        perm = '; '.join(f'{k}: {v}' for k, v in _dict(row.get('effective_permission')).items())
        out.append(f"| `{row.get('credential')}` {_cell(_str(row.get('name')))} | {_cell(perm)} | "
                   f"{row.get('reach')} | {'no' if row.get('relied_on') is False else 'yes'} | "
                   f"{_cell(_str(row.get('lifetime')))} | {row.get('status')} |")
    out += ['', '### Runner configuration invariants', '',
            '| `config.yaml` path | Rule | Value | Status |', '|---|---|---|---|']
    cfg = _dict(profile.get('runner_config'))
    for rule in _dicts(cfg.get('rules')):
        value = json.dumps(rule['value']) if 'value' in rule else '-'
        out.append(f"| `{rule.get('path')}` | {rule.get('rule')} | {_cell(value)} | "
                   f"{rule.get('status')} |")
    options = _dict(cfg.get('options'))
    out += ['', f"Declared `container.options` ({options.get('status')}, verify at "
                f"{_leaves(options.get('verify_at'))}): {_ids(options.get('declared'))}. Label: "
                f"`{_dict(cfg.get('label')).get('name')}` on "
                f"{_cell(_str(_dict(cfg.get('label')).get('image_rule')))}."]
    env = _dict(cfg.get('environment'))
    token_input = _dict(_dict(profile.get('registration')).get('token_input'))
    out += ['', f"Runner service environment ({env.get('status')}): never "
                f"{_ids(env.get('forbidden_names'))} or a name starting "
                f"{_ids(env.get('forbidden_prefixes'))}; config expansion "
                f"{env.get('config_expansion')}. Registration token ({token_input.get('status')}): "
                f"`{token_input.get('flag')}` under `{token_input.get('path_prefix')}` only; refused: "
                f"{_ids(token_input.get('refused'))}."]
    gitea = _dict(profile.get('gitea'))
    out += ['', '### Gitea-side configuration', '',
            '| Repository | Role | Private | Actions | Status | Verify at |',
            '|---|---|---|---|---|---|']
    for repo in _dicts(gitea.get('repositories')):
        out.append(f"| `{repo.get('repository')}` | {repo.get('role')} | "
                   f"{'yes' if repo.get('private') is True else 'no'} | "
                   f"{'enabled' if repo.get('actions_enabled') is True else 'disabled'} | "
                   f"{repo.get('status')} | {_leaves(repo.get('verify_at'))} |")
    other = _dict(gitea.get('every_other_repository'))
    out.append(f"| every other repository | proposal | {'yes' if other.get('private') else 'no'} | "
               f"{'enabled' if other.get('actions_enabled') else 'disabled'} | "
               f"{other.get('status')} | {_leaves(other.get('verify_at'))} |")
    ceilings = _dict(policy.get('ceilings'))
    out += ['', '| Ceiling at | Mode | Maximum per unit | Cross-repository grants |',
            '|---|---|---|---|']
    for row in _dicts(ceilings.get('owners')) + _dicts(ceilings.get('repositories')):
        perms = _dict(row.get('max_token_permissions'))
        values = sorted({str(v) for v in perms.values()})
        grants = row.get('allowed_cross_repo_ids', row.get('collaborative_owner_ids'))
        out.append(f"| `{row.get('owner') or row.get('repository')}` | "
                   f"{row.get('token_permission_mode')} | {', '.join(values) or '-'} on "
                   f"{len(perms)} units | {_cell(json.dumps(grants))} |")
    secrets = _dict(gitea.get('secrets'))
    out += ['', 'Secrets and variables: ' + '; '.join(
        f'{k}: {len(_list(secrets.get(k)))}' for k in SECRET_SETS) + '. Public repositories: '
        f"{len(_list(gitea.get('public_repositories')))}."]
    out += ['', '### Reach', '',
            '| Reach | From | To | Kind | Class | Credentials | Owner act | Status | Verify at |',
            '|---|---|---|---|---|---|---|---|---|']
    for row in _dicts(profile.get('reach')):
        out.append(f"| `{row.get('id')}` {_cell(_str(row.get('path')))} | `{row.get('from')}` | "
                   f"`{row.get('to')}` | {row.get('kind')} | {row.get('class') or '-'} | "
                   f"{_ids(row.get('credentials'))} | {row.get('owner_act') or '-'} | "
                   f"{row.get('status')} | {_leaves(row.get('verify_at'))} |")
    proxy = _dict(profile.get('proxy'))
    out += ['', f"Filtering proxy ({proxy.get('status')}, Owner act {proxy.get('owner_act')}), "
                'allowed: ' + '; '.join(
                    f"{_dict(r).get('method')} `{_dict(r).get('path')}`"
                    + (f" ({_dict(r).get('window')} window only)" if _dict(r).get('window') else '')
                    for r in _list(proxy.get('allow'))) + '. Denied: '
                + ', '.join(f'`{d}`' for d in _strs(proxy.get('deny'))) + '.']
    out += ['', '### Owner acts', '', '| Act | What | Class | Requested at | Status |',
            '|---|---|---|---|---|']
    for act in _dicts(profile.get('owner_acts')):
        out.append(f"| {act.get('id')} | {_cell(_str(act.get('act')))} | "
                   f"{_cell(_str(act.get('class')))} | {act.get('requested_at')} | "
                   f"{act.get('status')} |")
    out += ['', '### Gitea Actions facts at the pin', '',
            '| Fact | Verified | Where (path:lines at the pin) | Live at |', '|---|---|---|---|']
    for fact in _dicts(policy.get('gitea_facts')):
        where = '; '.join(f"`{_dict(s).get('path')}:{_dict(s).get('lines')}`"
                          for s in _list(fact.get('source'))) or '-'
        verified = {'source': 'at source', 'live': 'live', False: 'no'}.get(
            fact.get('verified') if isinstance(fact.get('verified'), (str, bool)) else None, '?')
        out.append(f"| {fact.get('id')}: {_cell(_str(fact.get('fact')))} | {verified} | {where} | "
                   f"{fact.get('verify_live_at') or fact.get('verify_at') or '-'} |")
    out += ['', '### Checks', '', '| Check | Codes | What |', '|---|---|---|']
    for row in _dicts(profile.get('checks')):
        out.append(f"| `{row.get('id')}` | {_ids(row.get('codes'))} | {_cell(_str(row.get('what')))} |")
    out.append('')
    return '\n'.join(out)


# -- loading ------------------------------------------------------------------------------

class Inputs:
    """What the profile and policy are checked against, loaded once under a root: the inventory,
    the network matrix, the role-token matrix, the lock, the decision records, the workflows,
    the profiles and the repository files the checks read (``csi.RepoFiles``)."""

    def __init__(self, root, inventory, matrix, role_tokens, lock, decisions, workflows, profiles,
                 files):
        self.root, self.inventory, self.matrix, self.role_tokens = root, inventory, matrix, role_tokens
        self.lock, self.decisions, self.workflows, self.profiles = lock, decisions, workflows, profiles
        self.files = files


def _read_json(root, rel):
    try:
        return json.loads((Path(root) / rel).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise LoadError(f'cannot read {rel}: {exc}') from exc


class LoadError(Exception):
    pass


def load_workflows(root, directory):
    out = {}
    base = Path(root) / directory
    if base.is_dir():
        for path in sorted(list(base.glob('*.yml')) + list(base.glob('*.yaml'))):
            try:
                out[f'{directory}/{path.name}'] = path.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                out[f'{directory}/{path.name}'] = None
    return out


def load_profiles(root):
    out = {}
    for path in sorted((Path(root) / 'profiles').glob('*/profile.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out[path.parent.name] = data
    return out


def load_inputs(root, profile):
    """Load the inputs ``evaluate`` takes from ROOT; raise LoadError when one cannot be read."""
    root = Path(root)
    decisions = {}
    if (root / 'decisions').is_dir():
        for path in sorted((root / 'decisions').glob('[0-9][0-9][0-9][0-9]-*.md')):
            decisions.setdefault(path.name[:4], path.name)
    directory = _str(_dict(_dict(profile).get('workflow')).get('directory')) or 'policy/ci/workflows'
    if Path(directory).is_absolute() or '..' in Path(directory).parts:
        directory = 'policy/ci/workflows'
    return Inputs(root, _read_json(root, INVENTORY), _read_json(root, MATRIX),
                  _read_json(root, ROLE_TOKENS), _read_json(root, LOCK), decisions,
                  load_workflows(root, directory), load_profiles(root), csi.RepoFiles(root))


def evaluate(profile, policy, inputs, readme_text=None, workflows=None, profiles=None):
    """The problems of PROFILE and POLICY against already-loaded INPUTS; WORKFLOWS ({rel: text})
    and PROFILES ({name: profile}), when given, replace the loaded ones."""
    return Checker(profile, policy, inputs, readme_text, workflows, profiles).run()


def check(profile, policy, root, readme_text=None):
    return evaluate(profile, policy, load_inputs(root, profile), readme_text)


def summary(profile, policy):
    lanes = {r.get('credential'): r.get('lane') for r in _dicts(_dict(policy).get('credential_lanes'))}
    facts = _dicts(_dict(policy).get('gitea_facts'))
    acts = _dicts(_dict(profile).get('owner_acts'))
    return (f"{len(_dicts(_dict(profile).get('lanes')))} lanes; validation job holds "
            f"{sum(1 for v in lanes.values() if v == 'validation-job')} and the runner host "
            f"{sum(1 for v in lanes.values() if v == 'validation-runner-host')} of "
            f"{len(lanes)} mapped credentials; {len(acts)} Owner acts "
            f"({sum(1 for a in acts if a.get('status') == 'observed')} observed); "
            f"{sum(1 for f in facts if f.get('verified') == 'source')} Gitea facts verified at "
            f"source, {sum(1 for f in facts if f.get('verified') == 'live')} live, "
            f"{sum(1 for f in facts if f.get('verified') is False)} unverified")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default='.', help='repository root (default: .)')
    parser.add_argument('--profile', help='CI runner control profile (default: '
                        '<root>/policy/ci-runner-profile.json)')
    parser.add_argument('--policy', help='CI token and secret policy (default: '
                        '<root>/policy/ci-token-secret-policy.json)')
    parser.add_argument('--readme', help='README with the generated block (default: the '
                        'profile\'s "readme" entry under the root)')
    parser.add_argument('--list', action='store_true',
                        help='also print the lanes, the Owner acts and the facts')
    parser.add_argument('--render', action='store_true',
                        help='print the README\'s generated block and exit')
    parser.add_argument('--live-report', metavar='FILE',
                        help='the Gitea-administration command\'s live report (an interface: '
                        'consumed from Q-02.3.1; refuses to run before)')
    args = parser.parse_args(argv)
    if args.live_report is not None:
        print('ERROR: --live-report is an interface only: the administration command\'s live '
              'check and its report arrive at Q-02.3.1 (decision 0016 section 6.6); nothing was '
              'read', file=sys.stderr)
        return 2
    root = Path(args.root)
    docs = []
    for given, default in ((args.profile, DEFAULT_PROFILE), (args.policy, DEFAULT_POLICY)):
        path = Path(given) if given else root / default
        try:
            docs.append((path, json.loads(path.read_text(encoding='utf-8'))))
        except (OSError, ValueError) as exc:
            print(f'ERROR: cannot read {path}: {exc}', file=sys.stderr)
            return 2
    (path, profile), (_, policy) = docs
    if args.render:
        sys.stdout.write(render(profile, policy))
        return 0
    try:
        inputs = load_inputs(root, profile)
    except LoadError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    readme_rel = args.readme or (profile.get('readme') if isinstance(profile, dict) else None)
    readme_text = None
    if readme_rel:
        readme_path = Path(args.readme) if args.readme else root / readme_rel
        try:
            readme_text = readme_path.read_text(encoding='utf-8')
        except OSError as exc:
            print(f'ERROR: cannot read {readme_path}: {exc}', file=sys.stderr)
            return 2
    problems = evaluate(profile, policy, inputs, readme_text)
    if args.list:
        for lane in _dicts(_dict(profile).get('lanes')):
            print(f"lane {lane.get('id')}: {', '.join(_strs(lane.get('domains')))} "
                  f"({lane.get('status')})")
        for act in _dicts(_dict(profile).get('owner_acts')):
            print(f"owner act {act.get('id')}: requested at {act.get('requested_at')} "
                  f"({act.get('status')})")
        for fact in _dicts(_dict(policy).get('gitea_facts')):
            print(f"fact {fact.get('id')}: verified {fact.get('verified')}")
    for problem in problems:
        print(f'FAIL {problem}')
    if problems:
        print(f'FAIL {path.as_posix()}: {len(problems)} problem(s)')
        return 1
    print(f'PASS {path.as_posix()}: {summary(profile, policy)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
