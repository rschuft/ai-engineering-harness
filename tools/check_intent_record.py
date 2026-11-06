"""Check the intent record of an OpenSpec proposal (plan leaf P-01.1).

The ``intent-driven`` OpenSpec schema (``catalog/openspec/schemas/intent-driven``)
carries an intent record in its proposal artifact, and the ``intent-normalization``
Agent Skill (``catalog/skills/intent-normalization``) produces it. The record format,
``intent-record/v1``, is specified in that Skill's ``references/intent-record.md``.
This checker is the harness's deterministic verifier for it: it reads a proposal and
the source text it quotes, and reports every violation of these invariants:

- each original quote is a byte-identical span of its source text;
- a proposed method attributed to the Owner is classified ``hypothesis`` unless it
  carries an acceptance reference, and every method that is a hypothesis links to a
  hypothesis item;
- a method taken from a quote is attributed to that quote's speaker;
- anything ``accepted`` or of claim type ``constraint`` carries an acceptance
  reference recorded separately from the request (never a quote's own source);
- every required section, field and item is present, with the claim types,
  attributions and authorities each section allows, and every reference resolves.

It runs no model and needs only the standard library. It checks the record's shape
and these invariants, not whether the objective is a good reading of the request:
that is the behavioural qualification of P-01.2. OpenSpec itself validates only the
delta specs of a change, not the proposal's content.

Usage (from the repository root):
    python -I -B tools/check_intent_record.py PROPOSAL --source REF=FILE [--source REF=FILE ...]

REF is a quote's ``source`` reference exactly as written in the proposal, and FILE
holds that source's text. Exit status: 0 PASS, 1 FAIL, 2 could not run.
"""
import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

RECORD_FORMAT = 'intent-record/v1'
RECORD_HEADING = 'Intent Record'
# OpenSpec's proposal parser (archive's proposal check) needs these level-2 headings.
OPENSPEC_HEADINGS = ('Why', 'What Changes')

CLAIM_TYPES = ('observation', 'requirement', 'constraint', 'hypothesis', 'unknown')
AUTHORITIES = ('proposed', 'accepted')
STATUSES = ('open', 'resolved')

ITEM_ID = re.compile(r'^(Q|O|C|M|H|AC|CL)([1-9][0-9]*)$')
# A reference to something outside the record: scheme:rest, no whitespace, no '='.
REFERENCE = re.compile(r'^[a-z][a-z0-9+.-]*:[^\s=,]+$')
ATTRIBUTION = re.compile(r'^(owner|(agent|person):[A-Za-z0-9._@/+-]+)$')
SKILL_REF = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*@[0-9]+\.[0-9]+\.[0-9]+$')
FIELD_LINE = re.compile(r'^- ([a-z_]+):(.*)$')
HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
FENCE_OPEN = re.compile(r'^(`{3,})text\s*$')
FENCE_CLOSE = re.compile(r'^ {0,3}(`{3,})\s*$')
BACKTICK_RUN = re.compile(rb'`+')


@dataclass(frozen=True)
class SectionSpec:
    prefix: str
    min_items: int
    required: tuple
    optional: tuple
    claim_types: tuple
    authorities: tuple = AUTHORITIES


SECTIONS = {
    'Original Quote': SectionSpec('Q', 1, ('source', 'attributed_to', 'claim_type'), (),
                                  ('observation',), ()),
    'Objective': SectionSpec('O', 1, ('statement', 'claim_type', 'attributed_to', 'source',
                                      'authority'), ('acceptance',), ('requirement',)),
    'Binding Constraints': SectionSpec('C', 0, ('statement', 'claim_type', 'attributed_to',
                                                'source', 'authority', 'acceptance'), (),
                                       ('constraint',), ('accepted',)),
    'Proposed Methods': SectionSpec('M', 0, ('statement', 'claim_type', 'attributed_to',
                                             'source', 'authority'),
                                    ('hypothesis', 'acceptance'),
                                    ('hypothesis', 'constraint')),
    'Hypotheses': SectionSpec('H', 0, ('statement', 'claim_type', 'attributed_to', 'source',
                                       'authority'), ('test',), ('hypothesis',), ('proposed',)),
    'Acceptance Criteria': SectionSpec('AC', 1, ('statement', 'claim_type', 'attributed_to',
                                                 'source', 'authority'), ('acceptance',),
                                       ('requirement',)),
    'Open Clarifications': SectionSpec('CL', 0, ('question', 'claim_type', 'attributed_to',
                                                 'source', 'consequence', 'status'),
                                       ('blocks', 'resolution'), ('unknown',), ()),
}
HEADER_REQUIRED = ('record_format', 'normalized_by')
HEADER_OPTIONAL = ('skill',)
UNKNOWN = object()   # lines under an unknown ### heading belong to no section


@dataclass(frozen=True)
class Problem:
    code: str
    where: str
    message: str

    def __str__(self):
        return f'{self.code} {self.where}: {self.message}'


@dataclass
class Item:
    id: str
    section: str
    line: int
    fields: dict = field(default_factory=dict)
    quote: bytes = None


@dataclass
class Record:
    header: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)   # title -> list of Item
    items: dict = field(default_factory=dict)      # id -> Item


def _lines(data):
    """Split bytes into (raw line with terminator, text without terminator)."""
    raw = data.split(b'\n')
    out = []
    for index, chunk in enumerate(raw):
        last = index == len(raw) - 1
        if last and chunk == b'':
            break
        line = chunk if last else chunk + b'\n'
        out.append((line, chunk.rstrip(b'\r').decode('utf-8')))
    return out


def _strip_terminator(data):
    if data.endswith(b'\n'):
        data = data[:-1]
        if data.endswith(b'\r'):
            data = data[:-1]
    return data


def _split_list(value):
    return [token.strip() for token in value.split(',')]


class _Parser:
    def __init__(self, data):
        self.lines = _lines(data)
        self.problems = []
        self.record = Record()

    def problem(self, code, where, message):
        self.problems.append(Problem(code, where, message))

    def outline(self):
        """Level-1/2 headings outside fences: list of (level, title, index)."""
        headings, fence = [], None
        for index, (_, text) in enumerate(self.lines):
            stripped = text.lstrip(' ')
            if fence:
                match = FENCE_CLOSE.match(text)
                if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                    fence = None
                continue
            opener = re.match(r'^ {0,3}(`{3,}|~{3,})', text)
            if opener and not (opener.group(1)[0] == '`' and '`' in stripped[len(opener.group(1)):]):
                fence = opener.group(1)
                continue
            match = HEADING.match(text)
            if match:
                headings.append((len(match.group(1)), match.group(2), index))
        return headings

    def parse(self):
        headings = self.outline()
        level2 = [(title, index) for level, title, index in headings if level == 2]
        titles = [title for title, _ in level2]
        for name in OPENSPEC_HEADINGS:
            if name not in titles:
                self.problem('missing-section', f'## {name}',
                             'OpenSpec reads this proposal heading; it is missing')
        records = [index for title, index in level2 if title == RECORD_HEADING]
        if len(records) != 1:
            self.problem('missing-section' if not records else 'duplicate-section',
                         f'## {RECORD_HEADING}',
                         f'expected exactly one, found {len(records)}')
            return self.record, self.problems
        start = records[0] + 1
        end = next((index for level, _, index in headings if level <= 2 and index >= start),
                   len(self.lines))
        self.parse_record(start, end)
        return self.record, self.problems

    def parse_record(self, start, end):
        index, section, item, in_comment = start, None, None, False
        seen_none = {}
        while index < end:
            raw, text = self.lines[index]
            lineno = index + 1
            index += 1
            if in_comment:
                in_comment = '-->' not in text
                continue
            if text.strip() == '':
                continue
            if text.lstrip().startswith('<!--'):
                in_comment = '-->' not in text
                continue
            heading = HEADING.match(text)
            if heading and len(heading.group(1)) == 3:
                title = heading.group(2)
                item = None
                if title not in SECTIONS:
                    self.problem('unknown-section', f'line {lineno}',
                                 f'"### {title}" is not a section of {RECORD_FORMAT}')
                    section = UNKNOWN
                    continue
                if title in self.record.sections:
                    self.problem('duplicate-section', f'### {title}', f'repeated at line {lineno}')
                section = title
                self.record.sections.setdefault(title, [])
                seen_none.setdefault(title, False)
                continue
            if heading and len(heading.group(1)) == 4:
                if section in (None, UNKNOWN):
                    self.problem('malformed-line', f'line {lineno}',
                                 'item heading outside a known section')
                    item = None
                    continue
                item_id = heading.group(2)
                spec = SECTIONS[section]
                match = ITEM_ID.match(item_id)
                if not match or match.group(1) != spec.prefix:
                    self.problem('bad-id', f'line {lineno}',
                                 f'"{item_id}" is not a {spec.prefix}<n> id for {section}')
                if item_id in self.record.items:
                    self.problem('duplicate-id', item_id, f'repeated at line {lineno}')
                item = Item(item_id, section, lineno)
                self.record.sections[section].append(item)
                self.record.items.setdefault(item_id, item)
                continue
            if heading:
                self.problem('malformed-line', f'line {lineno}',
                             f'unexpected heading level inside {RECORD_HEADING}')
                continue
            if text == 'None.' and section not in (None, UNKNOWN) and item is None:
                seen_none[section] = True
                continue
            fence = FENCE_OPEN.match(text)
            if fence and item is not None and item.section == 'Original Quote':
                index = self.read_quote(item, fence.group(1), index, end)
                continue
            match = FIELD_LINE.match(text)
            if match:
                key, value = match.group(1), match.group(2).strip()
                target = item.fields if item is not None else (
                    self.record.header if section is None else None)
                where = item.id if item is not None else 'header'
                if target is None:
                    self.problem('malformed-line', f'line {lineno}',
                                 f'field "{key}" outside an item')
                elif key in target:
                    self.problem('duplicate-field', where, f'"{key}" repeated at line {lineno}')
                elif value == '':
                    self.problem('missing-field', where, f'"{key}" is empty (line {lineno})')
                else:
                    target[key] = value
                continue
            self.problem('malformed-line', f'line {lineno}',
                         'expected a "- key: value" field, an item heading or "None."')
        for title, items in self.record.sections.items():
            if items and seen_none.get(title):
                self.problem('malformed-line', f'### {title}', '"None." alongside items')
            if not items and not seen_none.get(title):
                self.problem('empty-section', f'### {title}',
                             'no items: write the single line "None." when there are none')

    def read_quote(self, item, opener, index, end):
        if item.quote is not None:
            self.problem('quote-fence', item.id, 'more than one quote block')
        content = []
        while index < end:
            raw, text = self.lines[index]
            index += 1
            close = FENCE_CLOSE.match(text)
            if close and len(close.group(1)) >= len(opener):
                quote = _strip_terminator(b''.join(content))
                longest = max((len(run) for run in BACKTICK_RUN.findall(quote)), default=0)
                if len(opener) <= longest:
                    self.problem('quote-fence', item.id,
                                 f'the fence has {len(opener)} backticks; the quote contains a '
                                 f'run of {longest}, so the fence must be longer')
                item.quote = quote
                return index
            content.append(raw)
        self.problem('quote-fence', item.id, 'the quote block is not closed')
        item.quote = _strip_terminator(b''.join(content))
        return index


def _check_reference(problems, where, key, value, items, allowed_prefixes=None):
    tokens = _split_list(value)
    for token in tokens:
        if ITEM_ID.match(token):
            if token not in items:
                problems.append(Problem('unknown-reference', where,
                                        f'{key} names {token}, which is not in the record'))
            elif allowed_prefixes and ITEM_ID.match(token).group(1) not in allowed_prefixes:
                problems.append(Problem('bad-reference', where,
                                        f'{key} must name {"/".join(allowed_prefixes)} items, '
                                        f'not {token}'))
        elif allowed_prefixes or not REFERENCE.match(token):
            problems.append(Problem('bad-reference', where,
                                    f'{key} has "{token}": not an item id'
                                    + ('' if allowed_prefixes else ' or a scheme:reference')))
    return tokens


def check(proposal, sources):
    """Check proposal bytes against {source reference: source bytes}; return Problems."""
    try:
        parser = _Parser(proposal)
    except UnicodeDecodeError as exc:
        return [Problem('encoding', 'proposal', f'not UTF-8: {exc}')]
    record, problems = parser.parse()
    if f'## {RECORD_HEADING}' in {p.where for p in problems if p.code in
                                  ('missing-section', 'duplicate-section')}:
        return problems

    header = record.header
    for key in HEADER_REQUIRED:
        if key not in header:
            problems.append(Problem('missing-field', 'header', f'"{key}" is required'))
    for key in header:
        if key not in HEADER_REQUIRED + HEADER_OPTIONAL:
            problems.append(Problem('unknown-field', 'header', f'"{key}" is not a header field'))
    if 'record_format' in header and header['record_format'] != RECORD_FORMAT:
        problems.append(Problem('record-format', 'header',
                                f'"{header["record_format"]}" is not {RECORD_FORMAT}'))
    if 'normalized_by' in header and (not ATTRIBUTION.match(header['normalized_by'])
                                      or header['normalized_by'] == 'owner'):
        problems.append(Problem('bad-attribution', 'header',
                                'normalized_by must be agent:<id> or person:<id>'))
    if 'skill' in header and not SKILL_REF.match(header['skill']):
        problems.append(Problem('bad-reference', 'header', 'skill must be <name>@<x.y.z>'))

    for title in SECTIONS:
        if title not in record.sections:
            problems.append(Problem('missing-section', f'### {title}', 'section is missing'))
    for title, items in record.sections.items():
        if len(items) < SECTIONS[title].min_items:
            problems.append(Problem('missing-item', f'### {title}',
                                    f'needs at least {SECTIONS[title].min_items} item(s)'))

    quote_sources = {item.fields['source'] for item in record.sections.get('Original Quote', [])
                     if 'source' in item.fields}
    items = record.items
    for item in (i for section in record.sections.values() for i in section):
        spec = SECTIONS[item.section]
        f = item.fields
        for key in spec.required:
            if key not in f:
                problems.append(Problem('missing-field', item.id, f'"{key}" is required'))
        for key in f:
            if key not in spec.required + spec.optional:
                problems.append(Problem('unknown-field', item.id,
                                        f'"{key}" is not a field of {item.section} items'))
        claim = f.get('claim_type')
        if claim is not None and claim not in spec.claim_types:
            problems.append(Problem('bad-claim-type', item.id,
                                    f'"{claim}" is not allowed in {item.section} '
                                    f'(allowed: {", ".join(spec.claim_types)})'))
        if 'attributed_to' in f and not ATTRIBUTION.match(f['attributed_to']):
            problems.append(Problem('bad-attribution', item.id,
                                    f'"{f["attributed_to"]}" is not owner, agent:<id> or '
                                    'person:<id>'))
        authority = f.get('authority')
        if authority is not None and authority not in (spec.authorities or AUTHORITIES):
            problems.append(Problem('bad-authority', item.id,
                                    f'"{authority}" is not allowed in {item.section} '
                                    f'(allowed: {", ".join(spec.authorities or AUTHORITIES)})'))

        acceptance = f.get('acceptance')
        if acceptance is not None:
            if not REFERENCE.match(acceptance) or acceptance.startswith('missing:'):
                problems.append(Problem('bad-reference', item.id,
                                        f'acceptance "{acceptance}" is not a scheme:reference'))
            elif acceptance in quote_sources:
                problems.append(Problem('acceptance-not-separate', item.id,
                                        f'acceptance {acceptance} is the request itself; an '
                                        'acceptance must be recorded separately'))
            if authority == 'proposed':
                problems.append(Problem('bad-authority', item.id,
                                        'an item with an acceptance reference is accepted'))
        elif authority == 'accepted' or claim == 'constraint':
            problems.append(Problem('missing-acceptance', item.id,
                                    'accepted items and constraints need an acceptance reference'))
        if claim == 'constraint' and authority == 'proposed':
            problems.append(Problem('bad-authority', item.id, 'a constraint is accepted'))

        if item.section == 'Original Quote':
            ref = f.get('source')
            if ref is not None and not REFERENCE.match(ref):
                problems.append(Problem('bad-reference', item.id,
                                        f'source "{ref}" is not a scheme:reference'))
            if item.quote is None:
                problems.append(Problem('missing-field', item.id,
                                        'the quote block (```text fence) is missing'))
            elif item.quote == b'':
                problems.append(Problem('quote-not-in-source', item.id, 'the quote is empty'))
            elif ref in sources:
                if item.quote not in sources[ref]:
                    problems.append(Problem('quote-not-in-source', item.id,
                                            f'the quote is not a byte-identical span of {ref}'))
            elif ref is not None and REFERENCE.match(ref):
                problems.append(Problem('source-unavailable', item.id,
                                        f'no source text given for {ref}; pass --source {ref}=FILE'))
            continue

        if 'source' in f:
            cited = _check_reference(problems, item.id, 'source', f['source'], items)
        else:
            cited = []
        if item.section == 'Proposed Methods':
            owner = f.get('attributed_to') == 'owner'
            if acceptance is None and claim is not None and claim != 'hypothesis':
                problems.append(Problem('owner-method-not-hypothesis' if owner
                                        else 'method-not-hypothesis', item.id,
                                        'a proposed method without an acceptance reference is '
                                        'a hypothesis'))
            if claim == 'hypothesis' and 'hypothesis' not in f:
                problems.append(Problem('missing-field', item.id,
                                        'a method that is a hypothesis names its hypothesis item'))
            if 'hypothesis' in f:
                _check_reference(problems, item.id, 'hypothesis', f['hypothesis'], items, ('H',))
            speakers = {items[t].fields.get('attributed_to') for t in cited
                        if t in items and items[t].section == 'Original Quote'}
            if speakers and f.get('attributed_to') not in speakers:
                problems.append(Problem('method-attribution', item.id,
                                        'a method taken from a quote is attributed to its '
                                        f'speaker ({", ".join(sorted(s for s in speakers if s))})'))
        if item.section == 'Open Clarifications':
            status = f.get('status')
            if status is not None and status not in STATUSES:
                problems.append(Problem('bad-status', item.id, f'"{status}" is not open or resolved'))
            if status == 'resolved' and 'resolution' not in f:
                problems.append(Problem('missing-field', item.id,
                                        'a resolved clarification names its resolution'))
            if 'resolution' in f and not REFERENCE.match(f['resolution']):
                problems.append(Problem('bad-reference', item.id,
                                        'resolution must be a scheme:reference'))
            if 'blocks' in f:
                _check_reference(problems, item.id, 'blocks', f['blocks'], items,
                                 ('O', 'C', 'M', 'H', 'AC'))
    return problems


def summary(proposal):
    record, _ = _Parser(proposal).parse()
    counts = {title: len(items) for title, items in record.sections.items()}
    return ', '.join(f'{counts.get(title, 0)} {SECTIONS[title].prefix}' for title in SECTIONS)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('proposal', type=Path)
    parser.add_argument('--source', action='append', default=[], metavar='REF=FILE',
                        help="a quote's source reference and the file holding its text")
    args = parser.parse_args(argv)
    sources = {}
    try:
        for entry in args.source:
            ref, sep, path = entry.partition('=')
            if not sep or not REFERENCE.match(ref) or not path:
                parser.error(f'--source needs REF=FILE with REF a scheme:reference: {entry!r}')
            sources[ref] = Path(path).read_bytes()
        proposal = args.proposal.read_bytes()
    except OSError as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2
    problems = check(proposal, sources)
    if problems:
        print(f'FAIL {args.proposal} ({len(problems)} problem(s))')
        for problem in problems:
            print(f'  {problem}')
        return 1
    print(f'PASS {args.proposal} ({summary(proposal)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
