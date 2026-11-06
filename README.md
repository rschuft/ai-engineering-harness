# AI Engineering Harness

An adoption-first, open-source AI engineering harness that turns Owner intent into designed, implemented, reviewed, and verified software through established components, isolated execution, and source-backed evidence.

This repository is the **implementation target**, not a finished product. The bundled plan and prompts describe proposed work; **no task is marked complete by this seed**.

## Start the Overseer

1. Clone [`rschuft/ai-engineering-harness`](https://github.com/rschuft/ai-engineering-harness). Use a full clone: the seed was imported in commit `13197dd`.
2. Optionally run `task setup`, or the commands it wraps (see [`CONTRIBUTING.md`](CONTRIBUTING.md)). It checks prerequisites, verifies the seed and runs the tool tests. The Overseer can perform this check instead.
3. Launch Claude Code in the repository using your **existing Overseer agent**. Start a fresh session with `/clear` **before** giving the agent the startup instruction.
4. Give the Overseer the contents of [`OVERSEER_START.md`](OVERSEER_START.md) as one prompt. It will read the authoritative architecture and plan, select a ready leaf, consult Architect only when justified, dispatch implementation to Builder, inspect evidence and continue when authorized.

**Do not run the 136 individual prompts as one batch.** They're scoped resumption/targeted-dispatch prompts; the Overseer coordinates dependencies and parent acceptance. The existing Claude Code agent definitions select their own models.

## Canonical inputs

| Path | Purpose |
|---|---|
| [`AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html`](AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html) | Approved architecture reference for this implementation baseline. |
| [`AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json`](AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json) | **Canonical executable plan:** 136 Small leaves and parent acceptance groups; all initially Not started. |
| [`OVERSEER_START.md`](OVERSEER_START.md) | Delegation, scheduling, acceptance and recovery instructions for the Overseer. |
| [`task_prompts/`](task_prompts/) | One standalone Overseer prompt per executable task, for focused execution or resumption. |
| [`task_manifest.json`](task_manifest.json) | Task-to-prompt mapping, dependencies and content hashes. |
| [`AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.html`](AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.html) | Human-readable, interactive projection of the plan. |
| [`AI_Engineering_Implementation_Work_Packages_Small_Steps_2026-10-31.csv`](AI_Engineering_Implementation_Work_Packages_Small_Steps_2026-10-31.csv) | Importable CSV projection; not a second source of truth. |
| [`tools/verify_seed.py`](tools/verify_seed.py) | Standard-library-only, read-only integrity/graph check. `python -I tools/verify_seed.py` checks the working tree: contract and authority files must match `SEED_MANIFEST.json`, while ordinary files may evolve. `--baseline seed` verifies the original import strictly from git history. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md), [`Taskfile.yml`](Taskfile.yml) | Developer and operator commands, prerequisites, verified platforms, repository layout, and how to change integrity-tracked files. |

The plan references the original artifacts by their exact filenames. **Keep the canonical filenames and relative locations together** unless you intentionally regenerate all task prompts, manifests and links.

## Bootstrap boundaries

- This seed uses the **already installed Claude Code Overseer / Architect / Builder** agents. OpenHands, Gitea, managed VMs and the future orchestration platform **do not yet exist merely because the architecture names them**.
- `F-02` (“Create the umbrella repository and repeatable tasks”) must be reconciled against this **already created** GitHub repository; do not create another repository or treat seeding as completion of that package's actual acceptance proof.
- Prefer existing upstream OSS and simple, replaceable integrations. Do not duplicate conversation engines, task trackers, agent harnesses, approval systems or VM orchestrators without demonstrated need.
- Preserve Owner intent separately from proposed implementation approaches. Do not treat conversational speculation or AI summaries as adopted decisions.
- Keep untrusted execution away from Owner secrets, management APIs, privileged CI and protected effects. Never allow Builder or a model-generated artifact to self-approve a consequential operation.
- For a **public MIT-licensed repo**, inspect changes for credentials, personal machine paths, private datasets and third-party redistribution obligations before committing or pushing. `LICENSE` is supplied by the existing repository, not by this seed.
- No work is considered complete without observed evidence and applicable parent-level acceptance.

## Scope and provenance

The adoption-first open-source harness is **separate from the existing custom Tarinala Control Plane**. The architecture and plan were drafted October 31, 2026; the repo-ready seed was packaged November 5, 2026. Exact upstream versions and API compatibility must be verified by the appropriate implementation tasks. See [`SEED_MANIFEST.json`](SEED_MANIFEST.json) for package content hashes.

License for this repository: MIT. Third-party dependencies and downloaded artifacts retain their own licenses and notice obligations.
