# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.1.0

### Original Quote

#### Q1
- source: conversation:qual-01/message-1
- attributed_to: owner
- claim_type: observation

```text
The admin dashboard feels sluggish and dated. Can you make it snappier and more modern before the next release? People keep grumbling about it.
```

#### Q2
- source: conversation:qual-01/message-2
- attributed_to: owner
- claim_type: observation

```text
To answer your questions: "snappier" means the Orders overview should show its data within 2 seconds of opening it, on our normal office laptops. Only the Orders overview matters for now. Forget "more modern", that was me venting; it is not part of this. The next release is on 3 December.
```

### Objective

#### O1
- statement: When a user opens the Orders overview of the admin dashboard on one of the organisation's normal office laptops, it shows its data within 2 seconds, so it no longer feels sluggish.
- claim_type: requirement
- attributed_to: owner
- source: Q1, Q2
- authority: proposed

#### O2
- statement: The improvement described in O1 is available to users in the next release, scheduled for 3 December.
- claim_type: requirement
- attributed_to: owner
- source: Q1, Q2
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

None.

### Hypotheses

None.

### Acceptance Criteria

#### AC1
- statement: On a normal office laptop as defined in CL6, the Orders overview shows its data, as defined and measured per CL5, within 2 seconds of being opened in the release build (depends on CL5 and CL6).
- claim_type: requirement
- attributed_to: owner
- source: O1, Q2, CL5, CL6
- authority: proposed

#### AC2
- statement: The change that meets AC1 ships in the release scheduled for 3 December.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O2, Q2
- authority: proposed

#### AC3
- statement: The user complaints identified in CL4 that concern the Orders overview's speed are addressed, and the Owner confirms that the complaints they were hearing are covered (depends on CL4).
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL4
- authority: proposed

### Open Clarifications

#### CL1
- question: What does "snappier" mean concretely: which pages or interactions feel sluggish (initial load, navigation, tables, filters, saves), and what response-time target or improvement would count as fast enough?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines which parts of the dashboard are in scope, whether the work is front-end rendering, backend/query performance or both, and what measurable threshold proves success.
- status: resolved
- resolution: conversation:qual-01/message-2

#### CL2
- question: What does "more modern" mean to you: a visual refresh only (styling, typography, spacing), a change of layout and navigation, alignment with an existing design system or product, or something else? Is there a reference you have in mind?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Ranges from a small styling change to a substantial redesign, changing scope, cost, risk to existing admin workflows, and how success is judged.
- status: resolved
- resolution: conversation:qual-01/message-2

#### CL3
- question: Which release is "the next release", and what is its cutoff date? If both improvements cannot fit, which takes priority?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Fixes the time budget and therefore how much can realistically be delivered, and whether scope must be split across releases.
- status: resolved
- resolution: conversation:qual-01/message-2

#### CL4
- question: Who are the people grumbling (internal admins, customers with admin access, support staff) and what exactly have they complained about? Can you point to the complaints, in particular any about the Orders overview?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, Q2
- consequence: Shows whether the 2-second target on the Orders overview actually covers what users complain about, or whether some complaints (for example about filtering, paging or saving on that page) would remain unaddressed.
- blocks: AC3
- status: open

#### CL5
- question: What exactly counts as the Orders overview "showing its data", and how should the 2 seconds be measured: from the click or URL navigation until the first rows are visible, or until everything (all rows, totals, filters) is loaded and usable; on a first open or a repeated one; with which data volume or filters (a typical day, the largest set users open); and must it hold on every open or for a stated share of opens (for example 95%)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q2
- consequence: Defines the measurable test for AC1; the stricter readings (fully loaded, largest data volume, every open) may require substantially more work, possibly in backend queries as well as the front end, affecting cost and the 3 December deadline.
- blocks: O1, AC1
- status: open

#### CL6
- question: Which laptop model or specification counts as a "normal office laptop", and on which network should the 2 seconds hold (office LAN, office Wi-Fi, VPN from home)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q2
- consequence: Fixes the conditions under which AC1 is measured; slower hardware or remote network access makes the target harder to meet and may change which methods fit.
- blocks: O1, AC1
- status: open

## Why

The Owner reports that the admin dashboard feels sluggish and that people keep complaining about it. They have narrowed the goal to the Orders overview: when opened on a normal office laptop it should show its data within 2 seconds (O1), delivered in the release scheduled for 3 December (O2). This matters because the slow Orders overview is a source of ongoing complaints and hurts the productivity of the people who rely on it. The "more modern" request has been withdrawn by the Owner and is out of scope.

## What Changes

- The Orders overview of the admin dashboard shows its data within 2 seconds of being opened on a normal office laptop (measurement and conditions pending CL5 and CL6), checked against a baseline measured on the current release under the same conditions.
- The user complaints behind the request that concern the Orders overview's speed are addressed (pending CL4).
- The change ships in the release scheduled for 3 December.
- Other dashboard pages and any visual redesign are out of scope.
- No implementation method has been proposed yet; methods will be identified and evaluated in the design.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `admin-dashboard`: load performance of the admin dashboard's Orders overview; the exact path under openspec/specs/ is to be confirmed.

## Impact

Affects the Orders overview of the admin dashboard and possibly the backend services and queries that feed it, depending on where the time is spent and on how the 2-second target is measured (CL5, CL6). No visual or layout changes are planned. Delivery is bounded by the release on 3 December.