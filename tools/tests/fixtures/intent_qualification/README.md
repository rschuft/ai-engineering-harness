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
