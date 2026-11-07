# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

### Original Quote

#### Q1
- source: conversation:qual-07/message-1
- attributed_to: owner
- claim_type: observation

```text
If a customer cancels an order within 30 minutes of placing it, they should get their money back automatically, without having to contact support.
```

### Objective

#### O1
- statement: A customer who cancels an order within 30 minutes of placing it gets their money back without any action by support and without having to contact support.
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
- statement: When a customer cancels an order 30 minutes or less after placing it, a refund to that customer is issued without the customer contacting support and without any manual step by support staff.
- claim_type: requirement
- attributed_to: owner
- source: O1
- authority: proposed

#### AC2
- statement: The amount refunded for such a cancellation matches the money-back scope that CL1 settles (which charges are included and where the money goes).
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL1
- authority: proposed

#### AC3
- statement: The refund for such a cancellation is issued within the time limit that CL2 settles, measured from the moment of cancellation.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL2
- authority: proposed

#### AC4
- statement: The 30-minute window is measured from the time the order was placed to the time the customer cancels; the treatment of an order cancelled at exactly 30 minutes and of cancellations after 30 minutes follows CL4.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL4
- authority: proposed

### Open Clarifications

#### CL1
- question: What does "their money back" cover: the full amount paid including shipping, fees and taxes, or only the item price? Must it go back to the original payment method, or is store credit acceptable?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines the refund amount and destination, which changes the acceptance check and the payment integrations involved.
- blocks: AC2
- status: open

#### CL2
- question: How quickly must the refund be issued (or visible to the customer) after the cancellation, e.g. immediately, within minutes, or within a business day?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Sets the timing criterion and affects which approaches fit (synchronous refund versus a batched process).
- blocks: AC3
- status: open

#### CL3
- question: What should happen if the order has already been shipped or handed to fulfilment within the 30 minutes, or if the customer cancels only part of the order?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Decides whether the automatic refund applies unconditionally within the window or excludes or prorates some cases, changing scope and financial risk.
- blocks: O1, AC1, AC2
- status: open

#### CL4
- question: Is an order cancelled at exactly 30 minutes inside the window, and should cancellations after 30 minutes keep today's process unchanged?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Fixes the boundary of the rule and whether the change is limited to the first 30 minutes or also affects later cancellations.
- blocks: AC4
- status: open

## Why

Customers who change their mind shortly after ordering currently need help to get their money back. O1 asks that a customer who cancels an order within 30 minutes of placing it gets their money back automatically, without contacting support. This removes friction for customers and manual refund work for support in a common, low-risk case. The refund scope, timing, edge cases and window boundary are still open (CL1 to CL4).

## What Changes

- A customer who cancels an order within 30 minutes of placing it receives a refund without contacting support and without manual handling by support staff (AC1).
- The refunded amount and destination follow the scope to be settled in CL1 (AC2).
- The refund is issued within a time limit to be settled in CL2 (AC3).
- The 30-minute window is measured from order placement to cancellation, with its boundary and behaviour after the window to be settled in CL4 (AC4); handling of shipped or partially cancelled orders awaits CL3.
- No implementation method has been proposed yet; methods are to be evaluated in the design.

## Capabilities

### New Capabilities
- `orders/early-cancellation-refund`: automatic refund for orders cancelled by the customer within 30 minutes of placement, without support involvement.

### Modified Capabilities

## Impact

Likely affects order cancellation, payment refund processing, and support workflows for refunds; exact systems depend on the design and on the answers to CL1 to CL4.