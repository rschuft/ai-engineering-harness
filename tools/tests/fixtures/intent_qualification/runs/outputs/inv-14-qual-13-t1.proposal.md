# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

### Original Quote

#### Q1
- source: missing:relayed-phone-call-without-durable-reference
- attributed_to: owner
- claim_type: observation

```text
Customers on the Basic plan should be able to invite up to 3 team members. Right now they can't invite anyone.
```

### Objective

#### O1
- statement: A customer on the Basic plan can invite team members to their account, up to a limit of 3 team members.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

None.

### Hypotheses

None.

### Acceptance Criteria

#### AC1
- statement: A customer on the Basic plan who currently has no invited team members can send an invitation to a team member, and the invitation succeeds without a plan-related refusal.
- claim_type: requirement
- attributed_to: owner
- source: O1, Q1
- authority: proposed

#### AC2
- statement: A customer on the Basic plan can have up to 3 team members through invitations; whether the account holder and pending invitations count toward the 3 depends on CL2.
- claim_type: requirement
- attributed_to: owner
- source: O1, Q1
- authority: proposed

#### AC3
- statement: When a Basic plan customer has reached the limit of 3 team members, a further invitation is refused and the customer is told that the Basic plan limit has been reached; the exact refusal behaviour depends on CL3.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1
- authority: proposed

### Open Clarifications

#### CL1
- question: Can you give a durable reference for this request (for example a ticket, email or written message that confirms what was said on the phone call)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Without a durable source, the quote cannot be verified against the original words, and the request cannot be traced.
- blocks: O1
- status: open

#### CL2
- question: Does "up to 3 team members" mean 3 people in addition to the account holder, or 3 people in total including the account holder? Do pending (not yet accepted) invitations count toward the 3?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Each reading changes how the limit is checked and how many people a Basic team can actually have.
- blocks: AC2, AC3
- status: open

#### CL3
- question: What should happen when a Basic plan customer tries to invite a fourth team member: should the invitation be refused outright, or should the customer be offered an upgrade to another plan? And what should happen to existing Basic accounts that already have more than 3 team members, if any exist?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: This changes the user-facing behaviour at the limit, and may add work to handle existing accounts and the upgrade flow.
- blocks: AC3
- status: open

#### CL4
- question: Is "Right now they can't invite anyone" a defect, meaning Basic is meant to allow invitations already and something is broken, or a change to the Basic plan's entitlements, meaning Basic never allowed invitations?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: A defect is diagnosed and fixed. A change to entitlements is a product and pricing change and may need updates to plan descriptions, billing and customer communication. Scope and risk differ.
- blocks: O1
- status: open

## Why

Customers on the Basic plan cannot invite any team members at the moment. The Owner wants them to be able to invite up to 3 team members (O1). Until this works, Basic customers cannot collaborate with their team as intended. The exact meaning of the limit, the behaviour at the limit, and whether this is a defect or a plan change are still open (CL2, CL3, CL4).

## What Changes

- Customers on the Basic plan can successfully invite team members (AC1).
- Basic plan accounts are limited to 3 team members. How the limit is counted is pending CL2 (AC2).
- An invitation beyond the Basic plan limit is refused, and the customer is told why. The exact behaviour is pending CL3 (AC3).
- No method has been proposed. The approach will be chosen in the design, once CL4 establishes whether this is a defect or an entitlement change.

## Capabilities

### New Capabilities
- `team-invitations`: inviting team members to a customer account, and the per-plan limits on team size, including the Basic plan limit of 3.

### Modified Capabilities

## Impact

- The customer-facing flow for inviting team members.
- Plan entitlements for the Basic plan.
- Possibly plan descriptions, pricing pages and customer communication, if CL4 shows this is an entitlement change rather than a defect.
- Possibly existing Basic accounts, depending on CL3.