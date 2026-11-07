# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

### Original Quote

#### Q1
- source: conversation:qual-06/message-1
- attributed_to: owner
- claim_type: observation

```text
Password reset emails sometimes take over an hour to arrive, and people give up. Send them through Postmark instead of our own SMTP relay.
```

### Objective

#### O1
- statement: Password reset emails reach the requesting user promptly and reliably, so people do not give up on resetting their password while they wait.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

#### C1
- statement: Password reset emails are sent through Postmark, because Postmark is the only email processor that Legal has approved.
- claim_type: constraint
- attributed_to: owner
- source: M1
- authority: accepted
- acceptance: conversation:qual-06/message-3

### Proposed Methods

#### M1
- statement: Send password reset emails through Postmark instead of our own SMTP relay.
- claim_type: constraint
- attributed_to: owner
- source: Q1
- authority: accepted
- acceptance: conversation:qual-06/message-3
- hypothesis: H1

### Hypotheses

#### H1
- statement: Sending password reset emails through Postmark instead of our own SMTP relay (M1) makes them arrive promptly enough that people no longer give up (O1).
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: Measure the time from the reset request to delivery in the recipient's inbox, over the same period and the same recipient domains, for emails sent through the SMTP relay and through Postmark. Check whether the Postmark path removes the deliveries that took over an hour and meets the target agreed in CL2.

#### H2
- statement: The delay occurs in or after our own SMTP relay, and not earlier in our system (for example in the application's queueing or generation of the email).
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- test: Timestamp each slow password reset email at request time, at enqueue time, at hand-off to the relay and at delivery. Check whether most of the delay falls between hand-off and delivery.

### Acceptance Criteria

#### AC1
- statement: A user who requests a password reset receives the reset email within the delivery time agreed in CL2, for at least the share of requests agreed in CL2.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL2
- authority: proposed

#### AC2
- statement: Over a measured observation period, no password reset email takes over an hour from the user's request to its arrival.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, Q1
- authority: proposed

#### AC3
- statement: Every password reset email is sent through Postmark.
- claim_type: requirement
- attributed_to: owner
- source: C1
- authority: proposed

### Open Clarifications

#### CL1
- question: Is using Postmark a binding requirement, or may the design choose another way to get reset emails delivered quickly?
- claim_type: unknown
- attributed_to: agent:intake
- source: Q1
- consequence: If it is binding, M1 becomes a constraint and the design must use Postmark. If it is not, the design may evaluate other delivery methods.
- blocks: M1
- status: resolved
- resolution: conversation:qual-06/message-3

#### CL2
- question: Within what time must a password reset email arrive, and for what share of requests (for example 95% within 1 minute)? How is arrival measured?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, O1
- consequence: The target sets the pass/fail threshold of AC1. It also decides whether switching to Postmark alone is enough or further changes are needed.
- blocks: AC1
- status: open

## Why

Password reset emails sometimes take over an hour to arrive, and people give up on resetting their password. O1 is for reset emails to reach users promptly and reliably so that they complete the reset. Delayed resets lock users out of their accounts and lose them. The Owner has accepted sending these emails through Postmark as a binding constraint (C1), because Postmark is the only email processor that Legal has approved.

## What Changes

- Password reset emails are sent through Postmark instead of our own SMTP relay (C1).
- Password reset emails arrive within an agreed delivery time (AC1, pending CL2), and none takes over an hour (AC2).
- The design still has to test whether the Postmark switch removes the delay (H1) and whether the delay actually lies in the relay path (H2).

## Capabilities

### New Capabilities
- `auth/password-reset-email-delivery`: delivery of password reset emails through Postmark within an agreed delivery time.

### Modified Capabilities

## Impact

- The password reset email sending path in the authentication flow.
- A new dependency on Postmark: an account, API credentials or SMTP credentials, sender domain verification (SPF/DKIM) and error handling.
- Password reset emails no longer use our own SMTP relay.
- Monitoring of delivery time for password reset emails, so that AC1 and AC2 can be verified.