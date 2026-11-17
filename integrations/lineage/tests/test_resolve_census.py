"""The static census of lineage_resolve.py (plan leaf P-04.4; the I1 integration design, R2).

The acceptance recorder loads ``lineage_resolve.py`` for the objective resolver, and the Integration process loads the
acceptance recorder in process. So ``lineage_resolve.py`` must name no dispatch module, directly or through any
module it names: the attempt resolver, which reads the dispatcher's records, lives in ``lineage_attempt.py``.

The census is the Integration process's own (integrations/ownerhost/tests/test_structure.py): the repository modules a
module loads by file name, read from its syntax tree (a string constant ending in ``.py`` that names a file in its
package, a sibling package or tools/), followed transitively.
"""
import ast
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINEAGE_DIR = HERE.parent
REPO = LINEAGE_DIR.parents[1]

CATEGORY = 'unit'


def loaded_sources(path: Path) -> set:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.py'):
            for candidate in ([path.parent / node.value] + list(REPO.glob(f'integrations/*/{node.value}'))
                              + list(REPO.glob(f'tools/{node.value}'))):
                if candidate.is_file():
                    found.add(candidate.resolve())
    return found


def census(start: Path) -> set:
    modules = {start.resolve()}
    while True:
        more = set().union(*(loaded_sources(m) for m in modules)) - modules
        if not more:
            return {m.relative_to(REPO).as_posix() for m in modules}
        modules |= more


class NoDispatchModule(unittest.TestCase):
    def test_lineage_resolve_names_no_dispatch_module(self):
        names = census(LINEAGE_DIR / 'lineage_resolve.py')
        self.assertIn('integrations/lineage/lineage.py', names)        # the census reads what it should
        self.assertEqual(sorted(n for n in names if n.startswith('integrations/dispatch/')), [])

    def test_the_attempt_resolver_still_reads_the_dispatcher_s_records(self):
        """The falsifier's other side: the attempt module's census does reach the dispatcher's module."""
        self.assertIn('integrations/dispatch/dispatch_inputs.py', census(LINEAGE_DIR / 'lineage_attempt.py'))


if __name__ == '__main__':
    sys.exit(unittest.main())
