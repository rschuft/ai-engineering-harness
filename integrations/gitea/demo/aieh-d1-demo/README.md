# aieh-d1-demo

The demonstration repository of the AI Engineering Harness's first integrated
demonstration (D1): a tiny Python package, standard library only, with
`unittest` tests.

| Path | What |
|---|---|
| `aieh_d1_demo/` | The package. |
| `tests/` | Its tests. Run them offline, from this directory: `python -m unittest discover -s tests` (Python 3.8 or newer; no dependency and no network). |
| `openspec/` | The design: OpenSpec 1.16.0 changes under `openspec/changes/`, with the `intent-driven` schema in `openspec/schemas/`. |
| `backlog/` | The work: Backlog.md 1.55.3 tasks. Backlog.md alone owns their status. |

The demonstration's change is planned as one OpenSpec change and tracked as one
Backlog.md task that points at the change's accepted revision. Its
implementation is the work the contained D1 agent does.
