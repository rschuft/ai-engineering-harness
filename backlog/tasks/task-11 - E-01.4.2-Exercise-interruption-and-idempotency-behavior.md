---
id: TASK-11
title: 'E-01.4.2: Exercise interruption and idempotency behavior'
status: To Do
assignee: []
created_date: '2026-11-16T03:53:00Z'
updated_date: '2026-11-16T19:33:00Z'
labels: []
milestone: m-0
dependencies:
  - TASK-8
references:
  - >-
    AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json#E-01.4.2
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Plan contract: leaf E-01.4.2 of AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json (work_packages), "Exercise interruption and idempotency behavior". The plan keeps the acceptance contract, and the reference to it is the authoritative link; the title is the plan title, cut at a word boundary only where its file path would exceed 100 characters. The acceptance criteria below are its proof, checked equal to it by tools/plan_commitment.py. Committed by Commitment: I1 (evidence/bootstrap-log.md#commitment-i1-2026-11-16).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Same conversation is recovered without repeated effects; original E-01.4 proof satisfied.
- [ ] #2 Offline, against the fake, across a lost create response and a dispatcher restart at each step (before the create, after it, after the initial message): no second create and no second initial message, shown by the fake's call log, which records what the fake received.
- [ ] #3 Each answer the fake gives is an entry of the one fixture catalog, which E-01.7's fixture serves, and each field of it is, in the provenance table, of one of the four provenance classes of E-01.7's proof (a recorded observation; a value echoed from the request; a value derived by a rule pinned in an accepted decision, or in harness code outside the fixture that the production path itself runs; the fixture's label); an observation is cited to the committed record of the live run that observed it (F-04.2's lifecycle; where F-04.2 did not observe it, F-04.1c, the E-01.3.x or S-01.3.1 evidence, or the D1 run record of 2026-11-16), and only when the inputs that determine it equal the observed request's.
- [ ] #4 A clock-valued field (a creation, update or event time, an uptime or an idle time) is a recorded observation that reproduces its cited value unchanged, whatever the request's time, and is marked clock-valued.
- [ ] #5 A field of none of those classes is not served, and a request whose answer the dispatch path would read from such a field is refused with the fixture's label; the one exception is the fields the dispatch path reads of the event that records the dispatcher's own initial message, as the read-binding test records them (its source and the content that holds the message text), which are derived from the pinned upstream source and marked source-derived, not observed, their observed counterpart being E-01.6's; every other field of that event follows the rule above.
- [ ] #6 A test, recording at the answer boundary over the restart matrix and the dispatch suites, binds the fields the dispatch path reads to the catalog's fields marked read, and none of them is clock-valued or not served.
- [ ] #7 A transport event a test injects (a response withheld, a connection closed, a request that never arrives) is not a catalog answer and is listed with its row; an answer no cited run gave, other than the one that holds that source-derived exception, is a test knob outside the catalog, and no row of the restart matrix is decided by one.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Disposed of by planning (2026-11-16): PB-10, by the plan amendment of 2026-11-16 (I1 recovery): the proof and action are amended, and the criteria above are the amended proof. PB-11: a reading, recorded in the leaf's notes: at the three held points, 'Same conversation is recovered' reads as the blueprint's 'attach to existing run or report unknown state'; continuing on the same conversation is the plan's 23rd deferral. PB-12: answered in E-01.7's amended proof. No blocker remains for planning. See evidence/bootstrap-log.md#i1-recovery-disposed-2026-11-16
<!-- SECTION:NOTES:END -->
