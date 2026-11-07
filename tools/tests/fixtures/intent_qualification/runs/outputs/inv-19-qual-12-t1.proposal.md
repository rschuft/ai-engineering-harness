# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.1.0

### Original Quote

#### Q1
- source: conversation:qual-12/message-1
- attributed_to: owner
- claim_type: observation

````text
The deploy script fails on the new build server:

```
$ ./deploy.sh production
mkdir: cannot create directory '/opt/app/releases': Permission denied
```

Just run `deploy.sh` with sudo from now on.
````

### Objective

#### O1
- statement: Running the deploy script for production on the new build server completes successfully instead of failing because it cannot create the releases directory.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Run deploy.sh with sudo from now on.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

#### M2
- statement: Give the account that runs deploy.sh write access to /opt/app (or pre-create /opt/app/releases owned by that account) on the new build server so the script runs without elevated privileges.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: O1, H2
- authority: proposed
- hypothesis: H3

### Hypotheses

#### H1
- statement: Running deploy.sh with sudo (M1) makes production deploys on the new build server succeed (O1) without unwanted side effects such as root-owned release files or root-level access for the whole script.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: Run sudo ./deploy.sh production on the new build server; confirm it completes, then check ownership of the created files under /opt/app and that later steps, later deploys and the running application work with them.

#### H2
- statement: The failure is caused only by the account running deploy.sh lacking write permission on /opt/app on the new build server, and no further step of the script fails once the directory can be created.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- test: Compare owner and permissions of /opt/app and the deploying account on the new and the existing build servers; rerun the deploy after making the directory writable and see whether any later step fails.

#### H3
- statement: Granting the deploying account write access to /opt/app or /opt/app/releases (M2) makes production deploys on the new build server succeed (O1) without running the script as root.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: M2
- authority: proposed
- test: Adjust ownership or permissions on the new build server, run ./deploy.sh production as the normal deploying account and confirm it completes and the deployed release works.

### Acceptance Criteria

#### AC1
- statement: On the new build server, the production deploy (deploy.sh production, invoked as decided in CL1) runs to completion with exit status 0 and no "Permission denied" error, and a new release exists under /opt/app/releases.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL1
- authority: proposed

#### AC2
- statement: After a deploy on the new build server, the deployed release runs and a subsequent deploy also succeeds, i.e. the files left by the deploy do not break later deploys or the application.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1
- authority: proposed

#### AC3
- statement: Deploys from the existing build servers and for any other environments in scope still succeed as before.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL2
- authority: proposed

### Open Clarifications

#### CL1
- question: Is running deploy.sh with sudo a binding requirement, or is the goal only that deploys work on the new server, so that fixing the directory permissions or the server setup instead (without root) is acceptable?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, M1
- consequence: If sudo is binding, M1 becomes a constraint and the design must handle root-owned files and the security risk of running the whole script as root; if not, the design can choose a least-privilege fix such as M2.
- blocks: M1, M2, AC1
- status: open

#### CL2
- question: Does "from now on" mean every deploy (all servers and all environments), or only production deploys on the new build server?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines whether the change touches only the new server's setup or the deploy procedure everywhere, and which servers and environments AC3 must cover.
- blocks: AC3, M1
- status: open

#### CL3
- question: Who or what runs deploy.sh on the new build server (a person, a CI job, a service account), and is that account allowed to use sudo, possibly non-interactively?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: A CI or service account without passwordless sudo cannot use M1 as stated; it also changes which account must own /opt/app under M2.
- blocks: M1, M2
- status: open

## Why

Production deploys fail on the new build server because deploy.sh cannot create /opt/app/releases (Permission denied). The Owner wants production deploys from that server to complete successfully (O1). Until this is fixed, the new build server cannot be used to release to production. The Owner suggested running the script with sudo; that remains a hypothesis to evaluate against alternatives and its security implications.

## What Changes

- Running the production deploy on the new build server completes without a permission error and produces a new release under /opt/app/releases (AC1).
- Files created by a deploy do not prevent the application from running or later deploys from succeeding (AC2).
- Deploys from existing build servers and other in-scope environments keep working (AC3).
- How this is achieved (running deploy.sh with sudo, M1, or fixing permissions for the deploying account, M2) is still a hypothesis to be evaluated in the design, pending CL1 to CL3.

## Capabilities

### New Capabilities
- `deployment/build-server-deploy`: running the deploy script from a build server to an environment, including the permissions it needs on the target directories.

### Modified Capabilities

## Impact

- deploy.sh and the way it is invoked on the new build server (and possibly elsewhere, depending on CL2).
- Configuration of the new build server: ownership and permissions of /opt/app, the deploying account, and possibly sudo rules.
- Security: running the deploy as root would widen privileges and could leave root-owned files under /opt/app.