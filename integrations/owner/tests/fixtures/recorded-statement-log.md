# Bootstrap log (a throwaway harness log of the acceptance recorder's recorded-statement path)

This file is a test fixture of plan leaf E-05.12 (`integrations/owner/tests/test_recorded_statement.py`). It is
committed as `evidence/bootstrap-log.md` of a throwaway harness repository. The entry anchored
`owner-direction-d1-planning-2026-11-15` is a byte-for-byte copy of that entry of the real log, so that the
recorder's reading of a multi-line verbatim block is tested on its real shape; every other entry is SYNTHETIC and
records no Owner decision.

## Leaves

- <a id="fixture-before-decisions"></a>**2026-11-15: SYNTHETIC FIXTURE: an anchored entry before the Decisions section, verbatim.**

  > SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.

## Decisions

- <a id="owner-direction-d1-planning-2026-11-15"></a>**2026-11-15: Owner standing authorization: the D1 manifest's reconciliation inside OA-22 (j), given with the Owner's per-act direction on E-05.11's clause (11d) and E-05.1's design, verbatim.** Given in the product manager's session, which records it (decision 0018 point 7). Verbatim:

  > Resume D1 from the Engineering Manager's published
  > handoff at origin/main 4109b16.
  >
  > The native Claude Code execution path has been
  > demonstrated live in an isolated disposable guest.
  >
  > Resolve the two outstanding planning items.
  >
  > 1. E-05.11 acceptance
  >
  > Amend clause 11d to accept the observed isolation
  > evidence instead of requiring an in-memory search
  > of unrelated host credentials.
  >
  > The evidence includes:
  > - No host filesystem or credential mounts.
  > - An exact allowlist of admitted secrets.
  > - No host Claude configuration in the guest.
  > - Credential-name absence checks.
  > - Successful searches for the admitted token.
  > - No direct container egress.
  > - Verified guest teardown.
  >
  > Do not authorize reading my GitHub credentials
  > or host Claude login.
  >
  > Accept E-05.11 if its remaining evidence meets
  > the revised criteria. Do not repeat the live
  > qualification solely because the acceptance
  > wording changed.
  >
  > 2. E-05.1 design
  >
  > Finalize and accept the OpenSpec change for
  > aieh-d1-demo:
  >
  > Implement slugify(text) as a small Python function,
  > with appropriate unittest coverage.
  >
  > Choose sensible, explicit behavior for normalization,
  > whitespace, punctuation, case, empty input, and
  > non-ASCII text.
  >
  > Keep the demonstration intentionally small.
  >
  > Reconcile the manifest with the current native
  > execution profile and its digest.
  >
  > Make routine product and architectural decisions
  > under delegated authority.
  >
  > Preserve all completed engineering work.
  > Do not introduce additional qualification gates,
  > credential checks, or infrastructure work.
  >
  > Publish the verified planning amendments.
  >
  > Then provide the Engineering Manager with the
  > committed implementation-ready handoff so D1
  > can proceed to its draft pull request.
  >
  > No further Owner approval is required for these
  > planning decisions.

  **The product manager's reading (not the Owner's words):**
  - Item 1 is the Owner's own act under decision 0018 point 4.8 (changing an acceptance criterion), given per act, never standing: E-05.11's Owner-credential value search is replaced by the isolation evidence he lists, and no Owner credential value is read for it.
  - "Reconcile the manifest with the current native execution profile and its digest" is read inside OA-22 (j)'s envelope as presented on 2026-11-14 ([presentation](OA-31-consolidated-presentation-2026-11-14.md), section 6; approved in the [Owner's decision](#owner-decision-oa-31-2026-11-14)): the product manager's delegated D1 manifest promotions (decision 0018 point 3.3) over the demo repository `aieh-d1-demo` and its change, the qualified native profile at its current digest and its binding, the D1 agent assignment with no Skills, and E-01.3.2's disposable work-attempt entries; its exclusions, stops and expiry (D1's acceptance) are (j)'s. It widens nothing. The entry carries the title decision 0020 point 7 requires of a delegated promotion's basis because the 2026-11-14 grant was recorded under another title (the [2026-11-13 finding](#p-04-3-verdict-2026-11-13), item 2).
  - The E-05.1 design choices and the routine decisions are the product manager's under decision 0018 point 3, listed for the D1 milestone report.
  - A promotion's basis links this one entry. That the promotion's other entries lie inside (j) rests on this reading's link to (j), as decision 0020 point 9.2 discloses; each promotion's record says so.
- <a id="owner-decision-oa-31-2026-11-14"></a>**2026-11-14: Owner decision (SYNTHETIC FIXTURE): the request of the D1 demo change, verbatim.** Stands in for the entry the add-slugify change quotes as its request (its Q1's source). Verbatim:

  > OA-25: use aieh-d1-demo, a small Python package
  > with unittest tests. The requested change is
  > to implement slugify(text) with appropriate tests.
- <a id="fixture-owner-reaccept-2026-11-16"></a>**2026-11-16: Owner direction (SYNTHETIC FIXTURE): a later direction, verbatim.** Verbatim:

  > SYNTHETIC FIXTURE, not an Owner decision:
  > accept O1 of qual-05-api-rate-limiting again, as amended.
- <a id="fixture-undated"></a>**SYNTHETIC FIXTURE: an Owner direction without a date, verbatim.** Verbatim:

  > SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.
- <a id="fixture-no-verbatim-2026-11-15"></a>**2026-11-15: Owner direction (SYNTHETIC FIXTURE): an entry without a verbatim block.** SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.
- <a id="fixture-em-verdict-2026-11-15"></a>**2026-11-15: E-05.12 PASS (SYNTHETIC FIXTURE, engineering manager).** The engineer's report, quoted:

  > I accept O1 of qual-05-api-rate-limiting as proposed.
- <a id="fixture-owners-answers-2026-11-15"></a>**2026-11-15: Owner's answers (SYNTHETIC FIXTURE) to the engineering manager's questions, verbatim.**

  > I accept O1 of qual-05-api-rate-limiting as proposed.
- <a id="fixture-owner-fence-2026-11-15"></a>**2026-11-15: Owner direction (SYNTHETIC FIXTURE): a transcript before the Owner's words.** A shell transcript:

  ```text
  > accept O1 of qual-05-api-rate-limiting from the transcript
  ```

  > SYNTHETIC FIXTURE: accept O1 of qual-05-api-rate-limiting after the transcript.
- <a id="fixture-owner-nested-2026-11-15"></a>**2026-11-15: Owner direction (SYNTHETIC FIXTURE): a question quoted after the Owner's words.** Verbatim:

  > Keep qual-05-api-rate-limiting small.

  - The product manager's question to the Owner, quoted (not the Owner's words):
    > Shall I accept O1 of qual-05-api-rate-limiting now?
- <a id="fixture-owner-request-qual-05-2026-11-15"></a>**2026-11-15: Owner direction (SYNTHETIC FIXTURE): the qual-05 request copied into the log, verbatim.** Given in the main session:

  > Please add rate limiting to the public API so a single client can't take it down for everyone else. Use a fixed window of 100 requests per minute per IP.
- <a id="fixture-owner-terse-2026-11-15"></a>**2026-11-15: Owner direction (SYNTHETIC FIXTURE): terse, verbatim.**

  > done. Resolve the two outstanding planning items.

## Owner-directed maintenance items (no plan leaf covers these)

- <a id="fixture-after-decisions-2026-11-15"></a>**2026-11-15: SYNTHETIC FIXTURE: an anchored entry after the Decisions section, verbatim.**

  > SYNTHETIC FIXTURE, not an Owner decision: accept O1 as written.
