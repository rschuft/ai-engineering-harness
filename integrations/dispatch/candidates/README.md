# Manifest candidates

Approved-input manifests (`ai-engineering-harness/dispatch/approved-inputs/v1`) prepared for a promotion. A
file here approves nothing: `load_manifest` refuses any manifest inside the checkout, and a manifest is approved
only when the dispatch-input commands record its promotion
([integrations/owner](../../owner/README.md#the-dispatch-input-commands-plan-leaf-p-043)). The recorder also
refuses a candidate inside the checkout (`CANDIDATE_INSIDE_CHECKOUT`), so the promoting session copies the file
outside it first and checks the copy's sha256.

| File | What | Promoted by |
|---|---|---|
| `d1-approved-inputs.json` | **The D1 manifest** (plan leaf E-05.3; the commitment `commitment-d1-2026-11-15` in `evidence/bootstrap-log.md`, "The D1 manifest"): the repository `aieh-d1-demo`; the design `add-slugify` at its accepted commit C2 (`dd18102d...`); the profile `strong-windows-qemu-whpx` at the sha256 of its `profile.json` (version 1: after E-05.2; version 2: after D1 slice A1, whose route allowlist lists the conversation proxy's two tails, so the profile's routes pin changed, its one changed value); the binding (`aieh-d1-demo`, `implement`, that profile, the pin); the pin `d1-implement`: [`catalog/assignments/d1-implement.json`](../../../catalog/assignments/d1-implement.json) at the harness commit that added it, with its sha256. | the product manager, under decision 0018 point 3.3, inside OA-22 (j) (basis: the Owner's standing authorization `owner-direction-d1-planning-2026-11-15`) |

`test_d1_candidate.py` holds the D1 candidate to the checked-in files: the profile's sha256 and the assignment's.
When either changes, the test fails until the candidate is revised (its `version` the next position of the
promotion series) and promoted again; a promoted manifest is never edited in place.

`version` is the candidate's position in the live promotion series: `input_recorder.py status` shows the next
one. The D1 candidate says 2: version 1 (sha256 `6e6d17f1...723d`) was promoted on 2026-11-15, and version 2 is
version 1 with its version and its profile digest replaced and nothing else (`test_d1_candidate.py` rebuilds
version 1 from it and checks that sha256), so its promotion names version 1 as `previous`. If `status` shows
another next position, the candidate's `version` is that number and nothing else changes.
