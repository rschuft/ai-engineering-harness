# 0026 - Declared transport authority, the fixture profile and the Agent Server fixture

Status: Proposed - 2026-11-16, for plan leaves E-01.4.2, E-01.5, E-01.7, E-01.8 and U-01.2 (architect, gates C and
G). It authorizes no reserved act. Points 5 and 8 wait for planning's answers on E-01.7's and E-01.8's wording.

**Authority:** the I1 commitment and the Owner's direction of 2026-11-16 ("use deterministic execution fixtures and
the verified D1 evidence where appropriate";
[`evidence/bootstrap-log.md`](../evidence/bootstrap-log.md#owner-direction-i1-2026-11-16)); decisions 0001, 0013
(points 1 and 2), 0020 (point 6) and 0024, all unchanged; blueprint `#conversation` (UI-01).

**Gate:** the architect's work design for I1 (gates C and G), with the engineering manager's rulings
([`evidence/I1-integration-design-2026-11-16.md`](../evidence/I1-integration-design-2026-11-16.md)).

**Supersedes:** none.

## Decision
1. **Authority.** An attempt's authority is `live` or `fixture`. A profile declares `fixture` in its pinned route
   allowlist and in its declaration; absent means `live`. The allowlist's digest is in the policy inputs, so the
   authority is bound at reservation; no record format changes.
2. **Seams.** The Agent Server transport, the credential provider, the Gitea target and the inspect and pull
   observers each declare an authority (absent: `live`). The dispatch path requires each to equal the attempt's bound
   authority at its first use and refuses otherwise with a stable code and no call. The dispatch modules compare
   declared values and contain no fixture-specific path.
3. The fixture transport targets a literal loopback address and refuses an answer without the fixture's label.
4. **Labels.** A record of an attempt whose authority is not `live` carries it. A reader computes the authority from
   the reservation and treats a missing or contradicting label as unknown. In lineage, a node a fixture answered has
   authority mode `fixture` and a `fixture-authority` uncertainty; such a projection is never complete.
5. **The fixture profile is not an execution profile:** it has no tier, claims no property, cannot be launched, and
   is operational only as its conformance evidence shows. Contract conditions C1 to C7 are unchanged. It replays the
   native execution kind with a token derived from a public seed, from a fixture credential provider.
6. **The fixture.** One catalog of answers, each field cited, echoed, derived by a pinned rule, or the label; one
   deterministic core; scenarios advance by call count; a request outside the catalog is refused. It executes nothing
   it receives. Its result commit is built by decision 0024 point 4.4's rule over D1's recorded file changes.
7. **Faces.** One loopback listener: the dispatcher's face, and a read-only face for the Owner UI. The Owner UI never
   uses the dispatcher's face.
8. Agent Canvas at the pin is shown as its standalone application on its own loopback origin, served by upstream's
   static server, never in the origin that holds the Owner's session credential.
9. In I1 the engineering view's access is the fixture's public labelled value; the dispatcher-issued runtime
   credential of decision 0013 point 2 is built at U-03.1.

## Not decided here
The live session access and its forward (U-03.1, OA-07); a fixture for review or CI stages; raw recorded payloads as
committed evidence.

## Not verified
Agent Canvas in a real browser against the fixture; the standalone server's flags in use.
