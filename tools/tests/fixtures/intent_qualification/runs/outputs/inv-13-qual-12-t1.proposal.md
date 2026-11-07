# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

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
- statement: Deploying to production with the deploy script from the new build server completes successfully, and keeps doing so on later deploys, instead of failing when it creates the release directory.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Run `deploy.sh` with sudo from now on.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

#### M2
- statement: Give the account that runs `deploy.sh` write access to `/opt/app/releases` on the new build server, for example by creating the directory owned by that account, so the script runs without elevated privileges.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: Q1
- authority: proposed
- hypothesis: H3

### Hypotheses

#### H1
- statement: Running `deploy.sh` with sudo (M1) makes production deploys from the new build server succeed (O1) on every later run, with no new failures caused by root-owned files or by sudo prompting for a password in non-interactive runs.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: On the new build server, run `sudo ./deploy.sh production` and confirm it completes. Then run a second deploy the same way, and from the usual trigger (CI or human), and check that it also completes. Inspect the ownership of the files it created and confirm the application and later deploys can use them.

#### H2
- statement: The failure happens because the account running `deploy.sh` on the new build server has no write permission on `/opt/app`, so it cannot create `/opt/app/releases`. The cause is not a missing parent directory or a different path on that server.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: Q1
- authority: proposed
- test: On the new build server, check that `/opt/app` exists, its owner and mode, and which account runs the deploy. Compare these with a build server where the deploy works.

#### H3
- statement: Giving the deploy account write access to `/opt/app/releases` (M2) makes production deploys from the new build server succeed (O1) without running the whole script as root.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: M2, H2
- authority: proposed
- test: Grant the access on the new build server, run `./deploy.sh production` as the normal deploy account, and confirm it completes and a second run also completes.

### Acceptance Criteria

#### AC1
- statement: On the new build server, starting a production deploy in the normal way completes without the "cannot create directory '/opt/app/releases': Permission denied" error and leaves a new release in place.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, Q1
- authority: proposed

#### AC2
- statement: A later production deploy from the new build server, started the same way and without manual permission fixes in between, also completes successfully. Which way of starting it counts as normal depends on CL2.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL2
- authority: proposed

#### AC3
- statement: Production deploys from the existing build servers keep completing successfully after the change.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1
- authority: proposed

### Open Clarifications

#### CL1
- question: Is running `deploy.sh` with sudo a binding requirement, or is any fix acceptable that makes production deploys from the new build server work, such as giving the deploy account write access to `/opt/app/releases`?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, M1
- consequence: If sudo is binding, M1 is promoted to a constraint and the design only has to make it safe. If it is not, the design can prefer a least-privilege fix (M2) and avoid running the whole script and its children as root.
- blocks: M1, M2
- status: open

#### CL2
- question: Who or what runs the deploy on the new build server (a person in a terminal, or CI/automation), and does "from now on" mean this server only or every build server and environment?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Non-interactive runs need passwordless sudo or another mechanism, and applying the change to all servers and environments widens the scope and the risk of the change.
- blocks: AC2, AC3, M1
- status: open

#### CL3
- question: Is it acceptable for files and directories under `/opt/app/releases` to end up owned by root, and do the application or later deploy steps need them to be owned by a specific account?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, M1
- consequence: If root ownership is not acceptable, running with sudo alone would break the application or later deploys, and M1 would need extra steps or a different method.
- blocks: H1, AC2
- status: open

## Why

Production deploys from the new build server currently fail because `deploy.sh` cannot create `/opt/app/releases` (permission denied). O1 is to make production deploys from that server complete reliably on this run and on every later one. Until then, releases cannot be shipped from the new build server.

## What Changes

- Production deploys started from the new build server complete without the permission error and produce a release (AC1).
- Repeated deploys keep succeeding without manual fixes between runs (AC2).
- Deploys from the existing build servers keep working (AC3).
- How permissions are resolved is not decided yet. The Owner's suggestion to run `deploy.sh` with sudo (M1) and the alternative of granting the deploy account write access (M2) are hypotheses for the design to evaluate, pending CL1 to CL3.

## Capabilities

### New Capabilities
- `deployment/build-server-deploy`: running production deploys successfully from the build servers, including the new one.

### Modified Capabilities

None.

## Impact

- `deploy.sh` and how it is invoked on the new build server.
- Filesystem ownership and permissions of `/opt/app` and `/opt/app/releases` on the new build server.
- Possibly the sudo configuration and the CI/automation that triggers deploys, depending on CL1 and CL2.