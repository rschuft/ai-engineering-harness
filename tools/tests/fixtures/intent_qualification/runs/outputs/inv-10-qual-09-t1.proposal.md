# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

### Original Quote

#### Q1
- source: conversation:qual-09/message-1
- attributed_to: owner
- claim_type: observation

```text
Make sign-up more secure and faster. Maybe add 2FA? Not sure. Also the sign-up form takes forever on mobile.
```

### Objective

#### O1
- statement: Sign-up is more secure than it is today.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

#### O2
- statement: Sign-up is faster than it is today, including on mobile devices, where the sign-up form is reported to take far too long.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Add two-factor authentication (2FA) to sign-up (suggested tentatively: "Maybe add 2FA? Not sure.").
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

### Hypotheses

#### H1
- statement: Adding 2FA to sign-up (M1) makes sign-up more secure (O1) against the threats that matter, without making sign-up slower in a way that defeats O2.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: Check which threats identified in CL1 2FA at sign-up actually mitigates, and measure sign-up completion time with and without the 2FA step, on desktop and mobile, against the baseline from AC2.

### Acceptance Criteria

#### AC1
- statement: Each sign-up security threat agreed in answer to CL1 has a check (review or test) showing it is mitigated in the changed sign-up flow and was not mitigated before; depends on CL1.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL1
- authority: proposed

#### AC2
- statement: The sign-up time measure agreed in answer to CL2 (for example time to load the form or time from opening the form to a created account), measured on the mobile devices and networks agreed in CL3, meets the target agreed in CL3 and is lower than a baseline measured before the change; depends on CL2 and CL3.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O2, CL2, CL3
- authority: proposed

#### AC3
- statement: The same sign-up time measure on desktop is not higher after the change than the baseline measured before it, including any steps added for security; depends on CL2 and CL4.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, O2, CL2, CL4
- authority: proposed

### Open Clarifications

#### CL1
- question: What does "more secure" mean for sign-up: which threats or problems are you worried about (for example fake or bot accounts, account takeover after sign-up, weak passwords, sign-ups with someone else's email)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines the scope of O1, what AC1 checks, and whether 2FA (M1) or a different method fits the threat at all.
- blocks: O1, AC1, H1
- status: open

#### CL2
- question: What does "faster" and "takes forever" refer to: the form loading slowly, the form being slow to respond while typing, submission taking long, or the process having too many steps for the user?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Changes which time is measured in AC2 and AC3 and whether the work is about performance or about the flow's design.
- blocks: O2, AC2, AC3
- status: open

#### CL3
- question: What is the target for mobile sign-up time, and on which devices, browsers or app versions, and network conditions was the slowness seen?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Without a target and reference conditions AC2 cannot be passed or failed, and the slowness cannot be reproduced.
- blocks: AC2
- status: open

#### CL4
- question: If a security measure (such as 2FA) adds a step or time to sign-up, which goal takes priority, and how much extra time, if any, is acceptable?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: O1 and O2 can conflict; the answer decides whether methods like M1 are acceptable and sets the limit in AC3.
- blocks: AC3, M1
- status: open

#### CL5
- question: Do you want 2FA specifically (for example as a product or compliance requirement), or was it only one idea for improving security?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If 2FA is required it becomes a binding constraint once accepted; otherwise it remains one hypothesis to evaluate against alternatives in the design.
- blocks: M1
- status: open

## Why

The Owner wants sign-up to be both more secure (O1) and faster (O2), and reports that the sign-up form takes far too long on mobile. A slow sign-up loses new users before they ever arrive, and a weak one lets in accounts or risks that are costly later. What "secure" and "fast" mean concretely is still open (CL1 to CL4), and the two goals may pull against each other, so they must be clarified before a design is chosen.

## What Changes

- Sign-up becomes measurably more secure against the threats agreed in CL1 (AC1).
- Sign-up becomes measurably faster on mobile, against an agreed measure and target (AC2), and does not get slower on desktop (AC3).
- Adding 2FA (M1) is recorded as a tentative Owner suggestion, a hypothesis (H1) to be evaluated in the design, not a decided change.

## Capabilities

### New Capabilities
- `sign-up`: the account sign-up flow, its security properties and its performance on mobile and desktop. To be replaced by the existing capability path if sign-up is already specified under openspec/specs/.

### Modified Capabilities
None identified yet; depends on whether a sign-up capability already exists.

## Impact

Affects the sign-up form and flow (front end, including mobile) and the account-creation back end. Depending on the answers to CL1 and CL5, it may affect authentication services and third-party dependencies (for example a 2FA or verification provider). Exact code and systems are not yet known.