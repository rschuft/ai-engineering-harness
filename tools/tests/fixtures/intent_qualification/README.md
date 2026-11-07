# Intent-normalization qualification (plan leaf P-01.2)

Behavioural qualification of the `intent-normalization` Agent Skill
(`catalog/skills/intent-normalization/`) on live model runs, and the OpenSpec
artifacts recorded from them. Evidence and verdict:
[`evidence/P-01.2-intent-skill-qualification.md`](../../../../evidence/P-01.2-intent-skill-qualification.md).

## Layout

| Path | What |
|---|---|
| `corpus/qual-NN/item.json` | One request: its messages, grouped into turns, each with a stable reference `conversation:qual-NN/message-M` (one relayed message has none, on purpose) and its sender. |
| `corpus/qual-NN/message-*.txt` | The message texts, byte for byte. They are the sources the checker compares quotes with. |
| `corpus/qual-NN/expected.md` | The expected outcome, written **before** any run: the faithful objective, which methods must stay hypotheses, which ambiguities must become clarifications, what must not happen. The fidelity review compares outputs with it. |
| `commands/claude-headless.json` | The command template of the runs: Claude Code headless, tool-less, isolated as far as its flags allow. |
| `runs/ledger.jsonl` | One entry per model invocation, probes and superseded runs included: redacted command line, time, exit code, model, tokens, list cost, digests of the raw output and of the extracted proposal, the tool, MCP, skill and command lists the session reported at start, and the checker verdict. Raw outputs stayed in scratch; their SHA-256 is here. |
| `runs/outputs/inv-NN-qual-MM-tT.proposal.md` | The proposal each invocation returned, unchanged. |
| `openspec/` | The "versioned accepted OpenSpec artifacts": `config.yaml` (`schema: intent-driven`) and four changes whose `proposal.md` is a model output byte for byte. Only `qual-02-search-freshness` carries an accepted objective and criterion, and only it has a delta spec, written by the implementing agent from those accepted items. Run OpenSpec on it by copying `openspec/` into a scratch project together with `catalog/openspec/schemas/intent-driven/` under `openspec/schemas/`. |

The messages are synthetic. Where a message stands for the Owner accepting
something (`qual-02` message-2, `qual-06` message-3), it is a **fixture standing in
for the Owner**, not an Owner decision: it exists to show how the Skill and the
checker handle a separately recorded acceptance.

## Why here

The corpus, the curated outputs and the OpenSpec changes are test data for the
harness's checker and runner, not product: `catalog/skills/intent-normalization/` is
the directory shipped to managed projects, and every change there bumps the Skill's
version, so qualification data stays out of it. P-01.1 decided against an
`openspec/` directory at the repository root.

## Running

`tools/qualify_intent_skill.py` composes the prompts, runs the command template with
the working directory set to an empty scratch directory, extracts `proposal.md`,
checks it with `tools/check_intent_record.py` against the item's messages and appends
a ledger entry. Its tests use a fake model command. Files here are kept LF
(`.gitattributes`) because quotes are compared byte for byte.
