# Catalog

Agent Skills and OpenSpec schemas that the harness ships for the projects it
manages. They are product artifacts: this repository does not use them for its own
planning (its bootstrap authority is the blueprint, `decisions/` and the bootstrap
log).

| Path | What | Version | Plan leaf |
|---|---|---|---|
| `openspec/schemas/intent-driven/` | OpenSpec workflow schema: proposal (with the intent record), specs, design. `apply.requires` lists all three; no `apply.tracks`, because Backlog.md tracks implementation. | schema `version: 1` | P-01.1 |
| `skills/intent-normalization/` | Agent Skill that turns a request into the proposal's intent record (`intent-record/v1`). | `metadata.version` in `SKILL.md`; history in its `CHANGELOG.md` | P-01.1 |

Nothing here is qualified on model runs yet: the Skill's behavioural qualification
is plan leaf P-01.2. The deterministic checks are `tools/check_intent_record.py` and
its tests (see [`docs/development.md`](../docs/development.md#intent-records)).

## Using the schema in a project

OpenSpec 1.16.0 resolves a schema name first from the project
(`<project>/openspec/schemas/<name>/schema.yaml`), then from the user's data
directory, then from its built-ins. To use this one, copy
`openspec/schemas/intent-driven/` to `<project>/openspec/schemas/intent-driven/` and
set `schema: intent-driven` in `<project>/openspec/config.yaml` (or pass
`--schema intent-driven` to `openspec new change`). Check it with
`openspec schema validate intent-driven`.

The layout under `catalog/openspec/` mirrors that project layout, so the copy is one
directory.

## Using the Skill

`skills/intent-normalization/` is a directory in the
[Agent Skills format](https://agentskills.io/specification): `SKILL.md` with `name`
and `description` frontmatter, a `references/` file with the record grammar, and the
proposal template in `assets/`. It names no particular agent product, and an agent
that supports Agent Skills loads it from wherever that agent reads Skills.
`assets/proposal-template.md` must stay identical to the schema's
`templates/proposal.md`; a test enforces it.
