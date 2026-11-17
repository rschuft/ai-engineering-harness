# Research inventory

Research leads and candidate integrations that may inform the architecture later. No entry is adopted, none has
been evaluated here, and none is a design decision. This file is data, not authority.

**Where authority lives.**
- The design authority is the blueprint (`AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html`).
- Accepted decisions in [`decisions/`](../decisions/) refine it.
- The plan holds the proposed Work and its acceptance contracts.
- An entry here grants no authority, adds no criterion, dependency or task to any leaf, and is not Work.

**Provenance.**
- The Owner supplied these leads on 2026-11-17, in his direction to planning, Part B
  ([verbatim](../evidence/bootstrap-log.md#owner-direction-i1-final-2026-11-17)). They come from discussions held
  outside this repository.
- The product manager took them in, and the program manager challenged the placement (dispatch 4 of that planning
  pass).
- The sources were not evaluated, as directed: "Do not begin deep technical evaluations yet."

**How an entry is written.**
- **Status:**
  - `candidate`: recorded, not evaluated.
  - `proposed`: a decision record proposes it.
  - `accepted`: an accepted decision adopts it, and [`composition/`](../composition/) pins it.
  - `rejected`: an evaluation or a decision rules it out.
  - `deferred (existing deferral n)`: an existing entry of the plan's `deferred` list holds the lead or its capability
    class. That entry's reconsider condition governs any evaluation.
- **Source verification.** Nothing was fetched in this intake. The URLs are exactly as supplied. Every description of
  a project or paper is the lead as the Owner gave it, not a verified fact.
- **Three kinds of statement:**
  - **Fact**: what this repository's records show, cited.
  - **Owner's direction**: quoted verbatim from the log; it binds any evaluation.
  - **Hypothesis**: planning's or the lead's, unverified.
- **Boundaries every evaluation keeps:**
  - adoption first;
  - upstream sources stay external, pinned in `composition/`, unless adaptation is necessary (`AGENTS.md`, "Adoption
    first");
  - the harness's records stay authoritative. Derived records "carry references but are never an authority"
    ([`integrations/lineage/README.md`](../integrations/lineage/README.md)). Inferred links "remain candidate
    interpretations ... until an authorized actor adopts them" (blueprint `#authority`).
- **This harness and the Tarinala Control Plane are separate.** No entry assumes a component, interface or behaviour of
  the other system, and nothing transfers between them without an explicit architectural decision.
- **The evaluation route** is the blueprint's existing one (`#practical-workflows`, workflow 05): "Research → reuse
  decision → pin → integrate → qualify", classified ADOPT, ADAPT, IMITATE or AVOID.
  - An evaluation, if taken up, becomes its own leaf by a plan amendment (decision 0018 point 3, with the program
    manager's challenge).
  - Its outcome is recorded by the record that decides it: a decision in `decisions/`, a pin in `composition/`, or a
    deferral. This file only points to that record.
  - Where this file and those records disagree, they govern, and this file is corrected.

## Summary

| Id | Lead | Capability it could serve (blueprint) | Already represented | Earliest milestone (non-binding) | Status | Pointer from the plan |
|---|---|---|---|---|---|---|
| RL-01 | Floorplan | Architecture enrichment in repository onboarding and Knowledge refresh (`#knowledge`, `#components`) | The capability class: the Groma.md extension; K-01.1; lineage's non-authority rule. Floorplan itself is not represented. | I4 | candidate | K-01.1's notes |
| RL-02 | Plannotator | The Owner's review of plans and diffs, with annotations (`#experience`, `#decisions`) | In part: P-04.1 and P-04.4 (I1, passed); assistant-ui cards; Gitea review; D-01.1 and D-01.2; G-03.2. Plannotator itself is not represented. | I2, at D-01.2 | candidate | D-01.2's notes |
| RL-03 | OpenAI Symphony | Workflow orchestration (`#workflow`) | Deferral 1; OpenHands Automation (coupled, not selected); the dispatch path (E-01.x, decisions 0024 and 0027); E-04.2.1 | No gate requires it; no earlier than I2, and only on the trigger | deferred (existing deferral 1) | deferral 1 |
| RL-04 | OpenCodeReview | A replaceable automated-review capability (`#quality-pipeline`) | E-03.3.1 to E-03.4; Q-01.1 and Q-01.2; E-04.1 and E-04.3.1. OpenCodeReview itself is not represented. | I2 | candidate | E-03.4's notes |
| RL-05 | Cognee | A Knowledge engine (`#knowledge`) | Deferral 3; the LanceDB, AnythingLLM and Open Ontologies rows; the `#authority` inferred-links rule | I4, only on the trigger | deferred (existing deferral 3) | deferral 3 |
| RL-06 | Self-Harness, Meta-Harness, AHE, HarnessOpt-Bench | Governed harness optimization (`#components`, `#authority`) | Deferral 6; Opik / RSIHub; KNOW-01 | After I2 (inference), only on the trigger | deferred (existing deferral 6) | deferral 6 |
| RL-07 | Raw-RAG; The Trinity | Source-grounded Knowledge and capability graphs (`#knowledge`, lineage) | In large part: the `#authority` rule; K-02.2; K-03.3.1 and K-03.3.2; P-03.x; O-01.x; the lineage kinds | I4 | candidate | K-03.1's notes |

## RL-01: Floorplan, as an Architecture Enrichment Provider

- **URL (as supplied):** https://github.com/haydenschmitty/floorplan
- **Source verification:** none. Its owner, licence, maintenance and capabilities are unverified.
- **Problem it could solve (hypothesis).** A current architectural model of a repository (components, dependencies,
  flows), tied to the exact revision it describes, for onboarding and for refreshing Knowledge after changes. Its
  consumers would be the Architect, the planner, the engineer, impact analysis and Owner visualizations. No leaf
  derives one today.
- **Capability affected:** Knowledge ingestion and refresh (`#knowledge`). E-02.1, which is in plan milestone I1 but
  outside I1's commitment, is a possible consumer; nothing here changes it.
- **Owner's direction:** "Knowledge remains authoritative in the harness; Floorplan is not automatically the store of
  record." The evaluation covers "incremental refresh after repository changes, reconciliation, source attribution and
  the separation of extracted fact from inference".
- **Intended boundary (hypothesis):** a replaceable provider behind one adapter:
  repository revision → structural extraction (AST, symbols, APIs) → semantic architecture enrichment → normalized
  components, dependencies and flows → provenance-linked, revisioned Knowledge → its consumers. Its output is a
  derived record that names its source revision and provider version, and keeps what was extracted apart from what
  was inferred.
- **Facts: already represented.**
  - The capability class is the blueprint's optional extension Groma.md: "Software architecture map with Backlog
    links", adopted "When code and component impact needs a visual projection" (`#components`).
  - Blueprint `#architecture`: "Optional Knowledge and integration providers ... extend the system when a measured
    need appears. None is required to deliver the first coherent Owner-to-engineering experience."
  - The lineage README: derived records "carry references but are never an authority" (built under P-03.1).
  - An evaluation would be held to K-01.1's proof (I4, not started): "Indexed passage identifies original source,
    revision, range and authorized audience."
- **Depends on:** K-01.1; P-03.2 (passed in I1).
- **Evaluation is justified when** a committed leaf needs architectural context or impact analysis that source
  references and Groma.md cannot provide, or at the planning pass that commits K-01.1.
- **To evaluate then:**
  - the Owner's list above;
  - the licence and the upstream form (a package, an image or a service);
  - offline operation;
  - a comparison with Groma.md.

## RL-02: Plannotator, for plan and code review

- **URL (as supplied):** https://github.com/backnotprop/plannotator
- **Source verification:** none. Its local-first operation, plan and diff review, annotations, inbox and licence are
  unverified.
- **Problem it could solve (hypothesis).** The Owner's review of accepted specifications, plans and proposed code
  changes, with actionable feedback attached to an exact revision, without rebuilding an equivalent annotation UI.
- **Capability affected:** the Owner experience and decision presentation (`#experience`, `#decisions`), and the
  pull-request review of I2.
- **Owner's direction:**
  - "Explore reuse or integration rather than rebuilding equivalent UI from scratch."
  - "It must not replace the protected authorization recorder or force an Owner approval on every routine engineering
    action."
- **Intended boundary (hypothesis):** a presentation and annotation surface over records the harness already holds:
  the OpenSpec change at a revision, and the Gitea pull request diff at a commit.
  - An annotation becomes a record the harness already defines, such as a Gitea review comment or an OpenSpec
    revision, and takes its authority from that record, never from the tool.
  - It holds no credential beyond what its surface needs.
- **Facts: already represented, in part.**
  - P-04.1 and P-04.4: the Owner's acceptance of an objective in the Owner host (I1, passed; unchanged by this entry).
  - Blueprint `#components`: assistant-ui, "ADOPT for Owner shell and cards only".
  - Blueprint: "Git/Gitea owns revisions and authenticated reviews. Our UI is a projection".
  - U-03.1 and U-03.2: native Agent Canvas inspection.
  - D-01.1 and D-01.2 (I2): pull-request and merge-review rules.
  - G-03.2 (I3): the Owner's merge bound to an exact revision.

  Plannotator itself is not represented.
- **Depends on:** D-01.1 and D-01.2 (I2); E-04.1 (the finding records); P-04.2 (the authorization recorder, which it
  never replaces).
- **Evaluation is justified when** the Owner's review of a plan or diff needs annotations that Gitea's review and the
  outcome cards cannot carry, at the planning pass that commits D-01.2.

## RL-03: OpenAI Symphony, for workflow orchestration

- **URL (as supplied):** https://github.com/openai/symphony
- **Source verification:** none, including that this URL is the project described. Its workflow specification,
  issue-to-agent orchestration, workspace management, retries, recovery, language, licence and runtime are unverified.
- **Problem it could solve (hypothesis).** Unattended orchestration of many Work items to agents, with workspaces,
  retries and recovery.
- **Capability affected:** Workflow and Execution (`#workflow`, `#execution-qualification`).
- **Owner's direction:**
  - "Explore adapters or reusable orchestration mechanisms without assuming adoption of Symphony's implementation
    language, coding provider or entire runtime."
  - "Do not duplicate existing working orchestration without evidence of a meaningful gap."
- **Facts: already represented.**
  - The working orchestration is the harness's own dispatch path: the resolver, admission and dispatcher (E-01.x), the
    result path (decision 0024), and the dispatcher lock and recovery (decision 0027). Retries of a correction live in
    E-04.2.1's correction-attempt budget.
  - Blueprint `#workflow`: "One Work item — stage transitions without a workflow engine". OpenHands Automation "is
    available as a trigger source for cron and external events, not the mandatory coordination engine for Backlog
    items".
  - Blueprint `#components`: OpenHands Automation; DBOS, "When high-consequence operations need more than existing
    automation and reconciliation".
  - OpenHands Automation 1.30.1 is a coupled dependency, not a selection (`composition/compatibility-matrix.md`;
    `composition/candidates.json`).
  - Deferral 1, "Independent workflow engine / DBOS": "reconsider only on demonstrated recovery failure".
  - Related deferrals:
    - 14 and 15: resumption, and keeping an interrupted attempt's workspace;
    - 23: "at the first commitment whose proof requires an interrupted attempt to continue on its own conversation
      (unattended orchestration)";
    - 26: "a scheduler, a service, unattended orchestration".
- **Status:** deferred, under existing deferral 1, which points here. No new deferral.
- **Earliest milestone:** no milestone's gate requires it. The nearest overlap is I2's E-04.2.1 and E-04.2.2, which
  make one serial correction attempt. Consider it no earlier than I2, and only on the trigger.
- **Evaluation is justified when** deferral 1's condition is met (a demonstrated recovery failure of the native
  dispatch and receipts), or a commitment's proof requires unattended orchestration of more than one Work item. Either
  would also reopen deferrals 23 and 26.
- **To evaluate then:**
  - map its capabilities onto the dispatch path and name the overlap;
  - name a gap only from evidence;
  - compare it with OpenHands Automation and DBOS.

## RL-04: OpenCodeReview, as an automated-review capability

- **URL (as supplied):** https://github.com/alibaba/open-code-review
- **Source verification:** none, including that this URL is "OpenCodeReview". Its deterministic structural diff
  analysis, specialized AI review, defect identification, review orchestration and licence are unverified.
- **Problem it could solve (hypothesis).** I2's gate needs "A seeded regression is caught"; E-03.4's proof needs the
  reviewer to identify a seeded real defect. A deterministic structural pass might raise detection or lower cost.
- **Capability affected:** the quality pipeline (`#quality-pipeline`), including its shift-left stage.
- **Owner's direction:**
  - "Potential role: replaceable review capability in I2."
  - "Compare with the existing independent review method using measurable defect detection, review quality, runtime
    and maintenance cost."
  - "Preserve independent acceptance and CI enforcement. Do not substitute a model's review assertion for verified
    findings."
- **Intended boundary (hypothesis):** behind the harness's review contract.
  - Its findings are normalized as E-04.1's are: origin, revision, classification.
  - A finding counts only when it resolves to real modified lines (E-03.3.1's proof).
- **Facts: already represented.**
  - E-03.3.1 (I2, not started) plans to adopt the OpenHands reusable review Skill (blueprint sources: "Evidence-based
    independent review").
  - E-03.4 qualifies review as an independent blocking gate.
  - Q-01.1 and Q-01.2 (I2) run the deterministic repository-native checks.
  - E-04.1 and E-04.3.1 normalize the findings and re-run the targeted checks.

  OpenCodeReview itself is not represented.
- **Depends on:** E-03.3.1, E-03.4 and E-04.1.
- **Evaluation is justified when** E-03.4's qualification shows a detection gap, or at the planning pass that commits
  E-03.4, if that pass chooses the comparison. It adds no criterion to I2.
- **To evaluate then:** the Owner's measures, fixed before the run, on the same seeded defects; the licence; and how
  it runs inside the review lane's containment.

## RL-05: Cognee, as a Knowledge engine

- **URL:** none supplied; locate it before any evaluation.
- **Source verification:** none. Its ingestion, graph and retrieval capabilities are unverified.
- **Problem it could solve (hypothesis).** Ingestion, a relationship graph and retrieval over the harness's Knowledge,
  if the planned hybrid retrieval proves insufficient.
- **Capability affected:** Knowledge (`#knowledge`): K-01 to K-03, U-05.
- **Owner's direction:**
  - "Compare with the harness's existing Knowledge architecture and planned hybrid retrieval."
  - "Do not assume that adopting a graph platform is beneficial."
  - "Preserve raw evidence, authority, revision identity, supersession and source-backed retrieval."
  - "Derived representations should help navigate Knowledge, not silently replace its sources."
- **Facts: already represented.**
  - The planned Knowledge is SQLite FTS5 plus local embeddings (K-01.x, K-02.x), with source authority, visibility and
    supersession (K-03.x). K-03.3.1: "Retrieval cannot return a fabricated or deleted source as current authority."
  - Blueprint `#knowledge`: LanceDB Embedded is "ALTERNATIVE. Consider if SQLite extensions cannot satisfy the measured
    corpus/query workload"; AnythingLLM is "DEFER", being "duplicative for our existing Owner conversation and source
    indexing".
  - Blueprint `#components`: the Open Ontologies extension, "When explicit source references are insufficient for
    semantic discovery".
  - Blueprint `#authority`: inferred links "remain candidate interpretations ... until an authorized actor adopts
    them".
  - Deferral 3, "Full ontology/graph DB / separate vector server".
- **Status:** deferred, under existing deferral 3. Deferral 3 had a rationale but no reconsider condition; its
  condition is now: "Reconsider when hybrid SQLite retrieval demonstrably fails a K-01 to K-03 proof or the I4 gate, or
  when explicit source references prove insufficient for semantic discovery". It points here. No new deferral.
- **Earliest milestone:** I4, only on that condition.
- **To evaluate then:** against K-03's and K-03.4's tests (revocation, contradictions, refusal of fabricated memory,
  supersession); its licence; local operation.

## RL-06: Harness optimization and learning

- **Leads:** Self-Harness, Meta-Harness, AHE, HarnessOpt-Bench. No URLs were supplied; locate each before any
  evaluation.
- **Source verification:** none. These are names only.
- **Problem it could solve (hypothesis).** The harness proposes and tests improvements to its own workflows, prompts or
  configuration from execution evidence.
- **Owner's direction:**
  - The potential direction: "Execution evidence -> candidate harness or workflow improvement -> isolated evaluation ->
    held-out tests and invariant challenge -> governed promotion."
  - "The harness may propose and test improvements to itself, but must not autonomously grant itself new authority or
    promote unverified changes."
  - "This remains research, not an I1 implementation requirement."
- **Facts: already represented.**
  - Deferral 6, "Automated model self-improvement platform": "Evaluate only once observable engineering benchmarks
    justify complexity". Planning's reading is that harness optimization is held under it, together with the blueprint's
    Opik / RSIHub row: "Tracing, evaluations and controlled agent-improvement experiments", adopted "When we can measure
    real task improvement and regressions".
  - The blueprint's sources cite RSIHub, https://arxiv.org/abs/2610.32253 ("Controlled agent self-evolution
    evaluation"). This intake has not checked it either.
  - Blueprint `#agent-skills`: Opik is "DEFER — First store small contract-test evidence in Gitea Actions; avoid a new
    observability backend until needed".
  - Blueprint `#knowledge`, KNOW-01: "Future agent self-improvement may leverage indexed execution histories for
    held-out evaluation, but it is not a prerequisite for retrieval."
  - Granting authority and widening policy are reserved to the Owner (decision 0018 points 4.7 and 4.8). Promotion
    goes through the existing processes: the integrity process and an independent review.
- **Status:** deferred, under existing deferral 6, which points here. No new deferral.
- **Earliest milestone (inference):** after I2, once engineering benchmarks exist (seeded regressions, review
  findings), and only on deferral 6's condition.

## RL-07: Source-grounded Knowledge and capability graphs

- **Leads (as supplied):**
  - Raw-RAG: https://arxiv.org/abs/2610.30755
  - The Trinity: https://arxiv.org/abs/2610.36077
- **Source verification:** none. The titles, authors and claims are unverified, and the papers were not read.
- **The Owner's candidate implications, with what already exists:**
  1. "Derived graphs and summaries navigate to raw evidence rather than replacing it": already a fact here.
     - Blueprint `#authority`: inferred links "remain candidate interpretations ... until an authorized actor adopts
       them".
     - K-02.2's action: "without promoting summary to authority".
     - The lineage README: derived records "are never an authority".
  2. "Link Work, Attempts, capabilities, tests and evidence through explicit relationships": in part.
     - The lineage kinds already include `work`, `attempt`, `commit`, `review`, `ci` and `effect-receipt`
       (`integrations/lineage/README.md`; P-03.1 and P-03.2 passed in I1, unchanged).
     - O-01.1 keys on objective, task, attempt, SHA, CI, approval and effect.
     - Only capabilities, and individual tests as nodes, have no lineage kind today.
  3. "Keep exploration and improvement separate from authorization": in part, by the same `#authority` rule and by
     decision 0018 point 4.
- **Capability affected:** Knowledge (`#knowledge`: K-02.2, K-03.3.1, K-03.3.2) and lineage (P-03.x, O-01.x).
- **Status:** candidate. The Owner: "These are hypotheses requiring research and evaluation, not adopted architectural
  decisions."
- **Earliest milestone:** I4.
- **Evaluation is justified when** K-03.1 is designed: the remaining hypothesis (capability and test nodes) is then
  compared with the lineage schema and K-03's authority contract.

## Sources to verify before any evaluation

| Entry | What is to be verified |
|---|---|
| RL-01 | The owner, licence and maintenance of `haydenschmitty/floorplan` |
| RL-02 | Plannotator's licence and its local-first claims |
| RL-03 | That `github.com/openai/symphony` is the project described |
| RL-04 | That `alibaba/open-code-review` is "OpenCodeReview" |
| RL-05 | Cognee's URL, then the project itself |
| RL-06 | The URLs of Self-Harness, Meta-Harness, AHE and HarnessOpt-Bench, then each one |
| RL-07 | The titles and authors behind arXiv 2610.30755 and 2610.36077 |
