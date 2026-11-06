# AI Engineering Harness

AI Engineering Harness is an open-source engineering system that turns an Owner's intent into designed, implemented, reviewed and verified software.

It is adoption-first. It composes established open-source products, integrates them through small, replaceable modules, and builds custom software only where a demonstrated gap remains. The engineering focus is on reproducible, pinned compositions; evidence tied to exact revisions; enforced security boundaries between the Owner's trusted side and untrusted agent execution; and integration that stays maintainable as upstream projects evolve.

The project is under active development. This repository holds a working implementation foundation, not the completed application; see [Current status](#current-status).

## Architecture overview

The design authority is the [architecture blueprint](AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html). Its [overview](AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#overview), [system composition](AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#architecture) and [selected software](AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#components) sections are the best starting points. In brief:

- **Owner interaction and intent capture.** The Owner states a desired outcome in conversation. assistant-ui provides the Owner workspace for intent, outcomes and decisions. Original intent is kept separate from proposed solutions.
- **Architecture and specification management.** OpenSpec holds versioned objectives, proposals, specifications and designs.
- **Work planning and dependencies.** Backlog.md holds tasks, acceptance criteria, dependencies and readiness.
- **Agent orchestration and isolated execution.** The OpenHands Software Agent SDK and Agent Server run agent sessions, tools and workspaces in a contained, low-privilege environment with no access to Owner secrets or host management. Agent Canvas is the native engineering view (conversation, terminal, files, activity) and connects directly to the Agent Server. Coding providers such as Claude Code or Codex are user-supplied and replaceable.
- **Independent verification, governance and authorization.** Implementations are independently challenged and validated at exact revisions. Consequential effects require an Owner-only protected merge and run through a separate, isolated executor. No agent can approve its own effect.
- **Git-backed artifacts, provenance and delivery.** Git and Gitea hold revisions, reviews and decisions. A small local Integration Service links records across these products by stable references instead of copying their state. Delivery counts only when the actual effect is observed, never on an agent's report.

```mermaid
flowchart TB
    owner([Owner])
    subgraph interfaces [Interfaces]
        ui["assistant-ui<br/>intent, outcomes, decisions"]
        canvas["Agent Canvas<br/>native engineering view"]
    end
    integ["Integration Service<br/>small owned glue"]
    subgraph records [Source-of-truth records]
        spec["OpenSpec<br/>objectives and designs"]
        work["Backlog.md<br/>Work and dependencies"]
        git["Git and Gitea<br/>revisions, reviews, protected merges"]
    end
    subgraph isolated [Isolated execution]
        agents["OpenHands Agent Server and SDK<br/>agent sessions, tools, workspaces"]
    end
    verify["Independent verification and authorization<br/>CI, review, authorized effects"]

    owner --> ui
    owner --> canvas
    ui --> integ
    integ --> spec
    integ --> work
    integ --> git
    integ -->|dispatch ready Work| agents
    canvas --> agents
    agents -->|candidate revisions and evidence| git
    git --> verify
```

### Component status

OpenHands Software Agent SDK and Agent Server, Agent Canvas, assistant-ui, OpenSpec, Backlog.md and Gitea are **selected and locked**. Their exact upstream versions are recorded in the [compatibility matrix](composition/compatibility-matrix.md) and pinned by hash, integrity and digest in the [component lock](composition/lock/README.md).

**None of these components is integrated or operational yet.** The harness does not yet run OpenHands sessions, provision execution environments or provide the Owner application.

## Current status

The repository holds a working implementation foundation, not the completed application. Established so far:

- **Bootstrap.** The initial seed was imported and verified.
- **F-01: upstream composition.** Components were selected and locked, with a resolver that verifies every pinned artifact.
- **F-02: repository foundation.** Repository structure, developer commands, integrity verification and contributor documentation.
- **M-1.** The blueprint was reconciled with [decision 0001](decisions/0001-agent-server-dispatch-precondition-and-version-line.md).

In progress: **F-03.1**, the managed execution environment provider selection and isolation contract.

The [evidence log](evidence/bootstrap-log.md) records each verdict with its revision and evidence; it is where progress is recorded. Accepted decisions are in [`decisions/`](decisions/). The [plan](AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json) defines the work; its own status fields are its original baseline, not progress.

## Getting started

[`CONTRIBUTING.md`](CONTRIBUTING.md) is the onboarding reference: prerequisites, verified platforms, every developer command, and how to change integrity-tracked files. The minimal start is:

```
git clone https://github.com/rschuft/ai-engineering-harness
cd ai-engineering-harness
task setup
```

## Agent orchestration

This section is for operators who coordinate agent work on the repository. Ordinary contributors do not need it.

Implementation is coordinated by an Overseer agent, which delegates bounded tasks, one per dispatch, to a Builder agent and consults an Architect agent when a design question warrants it.

- [`CLAUDE.md`](CLAUDE.md): repository instructions for agents, including source precedence and authority boundaries.
- [`OVERSEER_START.md`](OVERSEER_START.md): Overseer startup, delegation, continuation and recovery instructions.
- [`task_prompts/`](task_prompts/): one scoped implementation prompt per plan task, indexed by [`task_manifest.json`](task_manifest.json). They are used through Overseer coordination, which handles dependencies and parent acceptance. They are not a batch execution script, but they do support targeted execution and recovery of an individual task.

## Repository guide

| Looking for | Go to |
|---|---|
| Architecture | [Blueprint](AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html) |
| The plan | [Canonical JSON](AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json), with an [HTML view](AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.html#roadmap) and a [CSV view](AI_Engineering_Implementation_Work_Packages_Small_Steps_2026-10-31.csv) |
| Developer setup and commands | [`CONTRIBUTING.md`](CONTRIBUTING.md), [`Taskfile.yml`](Taskfile.yml) |
| Implementation evidence | [`evidence/`](evidence/) |
| Decisions | [`decisions/`](decisions/) |
| Component selection, locks and licence inventory | [`composition/`](composition/) |
| Agent operating instructions | [`CLAUDE.md`](CLAUDE.md), [`OVERSEER_START.md`](OVERSEER_START.md), [`task_prompts/`](task_prompts/) |

The blueprint, plan and task prompts are integrity-tracked; [`CONTRIBUTING.md`](CONTRIBUTING.md#changing-integrity-tracked-files) explains how to change them.

## Provenance

The repository was bootstrapped from a seed that was imported at commit `13197dd` ([bootstrap entry](evidence/bootstrap-log.md#bootstrap)). The original import can still be verified strictly from git history, in a full clone:

```
python -I tools/verify_seed.py --baseline seed
```

## Scope and licence

- This project is separate from the existing custom Tarinala Control Plane.
- Repository-owned code is licensed under the [MIT License](LICENSE).
- Third-party components and artifacts keep their own licences and distribution obligations. Licence compliance of the composition is not yet verified; open items are tracked in the [licence ledger](composition/inventory/LEDGER.md).
