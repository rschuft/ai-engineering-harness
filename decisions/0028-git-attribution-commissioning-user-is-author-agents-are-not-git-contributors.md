# 0028 - Git attribution: the commissioning user is the author; agents are not git contributors

Status: Accepted - 2026-11-16, by the engineering manager (decision 0018 points 1 and 3.1). It records and applies the
Owner's governing direction of 2026-11-16 (evidence: the log entry owner-direction-git-attribution-2026-11-16, which
quotes it verbatim). It authorizes no reserved act.

**Authority:** the Owner's direction of 2026-11-16 (third message, governing). Also: decision 0012 (the `aieh-owner`
authority identity and its separately authorized merge); decision 0024 point 4 (the result commit's identity, which
this record supersedes for new commits as point 6 says); decision 0025 (the Integration process and its two writes,
point 8); and plan leaves P-01.3, P-04.4, E-01.8 and U-06.1.

**Supersedes:** decision 0024 point 4's committer and author identity (`aieh-bot-builder <aieh-bot-builder@localhost.invalid>`),
for commits made after this record, from leaf E-01.8 on. Existing history is not rewritten.

## Context

On 2026-11-16 the engineering manager ruled that P-01.3's capture commit would carry a fixed component identity,
`aieh-owner-host <aieh-owner-host@localhost.invalid>`, as both author and committer. The Owner corrected the ruling three
times. The third direction governs: the harness performs engineering work on behalf of its users, and AI agents are
implementation mechanisms, not independent git contributors.

## Decision

1. **Author.** The git author of a change commissioned by a user is that user's explicitly configured,
   provider-associated git identity. This holds whether the user wrote the content or an AI agent generated it on the
   user's behalf.
2. **Committer.** The committer is the identity that actually performs the commit.
   - When the harness commits under the user's identity, the committer is the user's configured identity.
   - When it commits through a service account, the committer is that account's legitimate, provider-associated
     identity.
   - In I1, every commit the harness makes on a user's behalf is made under the user's identity: P-01.3's capture,
     P-04.4's acceptance, and E-01.8's result.
3. **No agent identities.** No git account or identity exists for an AI agent, a model or an agent role.
   - Agent identity, model, execution, provenance and contribution are recorded in the harness's evidence and lineage
     records: the intent record's `normalized_by`, the attempt and its receipts, and the lineage projection.
4. **Binding to the user.** The identity is configured per authenticated user and looked up by the session's
   principal.
   - It is never a shared default, and never the installation owner's identity for another user's work.
   - It is never read from git config or the environment, and never inferred.
5. **Validity and privacy.**
   - **Grammar:** `Name <email>`.
   - **Placeholders:** an invented placeholder domain (`.invalid`, `.localhost`, `.example`, `.test`, `localhost`) is
     refused.
   - **Noreply addresses:** a provider-associated noreply address is supported.
   - **Other addresses:** a personal address appears only because the user configured it explicitly.
   - **Unavailable identity:** if a required identity is absent or invalid, the write is refused with a stable code
     and nothing is written. No identity is substituted.
6. **Authorization and history.** Git authorship grants nothing.
   - The authorization stays in its own records: decision 0012's recorder, the Owner's recorded acts, and the
     session.
   - `aieh-owner` is never used for a routine commit. The recorder's merge, a separately authorized operation, is
     unchanged.
   - Existing D1 history is not rewritten.

## Consequences

- **The Owner configures his identity at the I1 demonstration** (the governing direction's item 12), presented with
  OA-32 and OA-33. Until then, the capture and acceptance writes refuse.
- **E-01.8 (slice 11)** applies point 2 to the result commit instead of decision 0024 point 4's bot identity. If
  E-01.8's "unchanged" clauses conflict with that, it is a question for planning.
- **The harness's Gitea service accounts** are registered with `localhost.invalid` emails (`gitea_host.EMAIL_DOMAIN`).
  A future commit made through a service account needs that account's legitimate, provider-associated identity first.
  This is discovered work for planning.

## Not decided here

- Which service account, if any, commits for an automated act that no user commissions.
- How a provider association is verified mechanically. Offline, the harness checks only the grammar and refuses
  placeholder domains.

## Not verified

- A commit read back from the Owner's real configured identity. That happens at the I1 demonstration.

## Current facts (2026-11-16, at P-01.3's verdict)

Point 5's placeholder list is applied as its intent ("an invented placeholder domain") requires. It also covers:
- the RFC 2606 names `example.com`, `example.net` and `example.org`, and their subdomains;
- `.local`, `.internal`, `.home.arpa` and `.lan`;
- IP-literal domains: bracketed, bare, or with an all-digit last label;
- single-label domains.

The email must be ASCII, and the name must hold a visible character and no format or control character. `.onion` stays
accepted. The capture enforces this (`integrations/ownerhost/capture.py`, `check_git_identity`; the log entry
p-01-3-verdict-2026-11-16).
