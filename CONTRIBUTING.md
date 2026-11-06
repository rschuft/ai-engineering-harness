# Contributing

You contribute to AI Engineering Harness by working with an AI coding agent,
such as Claude Code or Codex. You describe the change you want. The agent reads
this repository's instructions, discovers its tooling, prepares what it needs,
makes the change and checks it. You review the result before anything is
published.

You do not need to know Python, Node.js, Task, the component resolver or the
project's implementation roadmap before you start. One coding agent is enough.

## 1. Install Git and clone the repository

Install Git from <https://git-scm.com/downloads>, then clone the repository:

```
git clone https://github.com/rschuft/ai-engineering-harness
cd ai-engineering-harness
```

Keep the normal full clone: some checks read the repository's history.

## 2. Install a coding agent

Use any capable coding agent that reads repository instruction files. Install it
with its official instructions, which are kept current there:

- **Claude Code:** [Set up Claude Code](https://code.claude.com/docs/en/setup),
  then the [quickstart](https://code.claude.com/docs/en/quickstart).
- **Codex:** the [Codex CLI](https://developers.openai.com/codex/cli) or the
  [Codex IDE extension](https://developers.openai.com/codex/ide); source and
  releases are at [github.com/openai/codex](https://github.com/openai/codex).

## 3. Open the repository with your agent

Start the agent in the directory you cloned, or open that folder in an editor
that runs the agent. The agent picks up the repository's instructions:
[`AGENTS.md`](AGENTS.md) for Codex and other compatible agents, and
[`CLAUDE.md`](CLAUDE.md), which includes `AGENTS.md`, for Claude Code.

## 4. Describe the change

Tell the agent what you want, in your own words. For example:

> I want to *describe the change here*. First read the repository's instructions.
> Discover the existing tooling and its prerequisites, and prepare an appropriate
> development environment. Then implement the change, run the relevant checks,
> and explain the result: what you changed, what you verified and how, and what
> remains unverified. Ask me before any privileged host change, credential use,
> security change or destructive operation.

The agent should handle routine environment preparation itself where its tools
support it and you allow it. Privileged host changes (administrator installs,
system settings), access to credentials, security changes and destructive
operations still need your explicit approval.

## 5. Review before publishing

Before you commit, push or open a pull request, review:

- **The changes.** The diff does what you asked and nothing else, and holds no
  secrets, personal machine paths or private data. This repository is public.
- **The verification.** Which checks ran, their results, and what the agent
  could not verify.
- **Consequential actions.** Anything the agent installed, downloaded or
  configured outside the repository, and anything it proposes to push or
  publish.

Commits and pushes pass through a publication-safety gate (git hooks that stop
credentials and personal machine paths). Your agent installs it once per clone;
see [Publication-safety gate](docs/development.md#publication-safety-gate).
Never bypass it with `--no-verify`.

## More detail

- [`docs/development.md`](docs/development.md): the technical reference, with
  prerequisites, verified platforms, every repository command and its direct
  equivalent, tool checksums, how to change integrity-tracked files, and the
  security safeguards.
- [`AGENTS.md`](AGENTS.md): the instructions every coding agent follows here.
- [`README.md`](README.md): what the project is and its current status. Its
  section [How work is done here](README.md#how-work-is-done-here) explains how
  the Owner's current implementation arrangement (the Overseer, Architect and
  Builder agents) differs from ordinary contribution. You do not need those
  agents.

Repository-owned code is licensed under the [MIT License](LICENSE).
