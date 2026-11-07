# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.1.0

### Original Quote

#### Q1
- source: conversation:qual-04/message-1
- attributed_to: owner
- claim_type: observation

```text
We need a CSV export of the customer list for the sales team. You MUST use pandas for this, no discussion. And it has to open properly in Excel for the München office — last time all the umlauts (ä, ö, ü, ß) came out as garbage.
```

#### Q2
- source: conversation:qual-04/message-2
- attributed_to: owner
- claim_type: observation

```text
pandas isn't a hard requirement, I just like it. München uses German Excel, so semicolons as separators. Export all active customers, with name, email and city.
```

### Objective

#### O1
- statement: The sales team can obtain the customer list as a CSV file that opens properly in Excel at the München office, with German characters such as ä, ö, ü and ß shown correctly instead of garbage.
- claim_type: requirement
- attributed_to: owner
- source: Q1, Q2
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Use pandas to produce the CSV export. The Owner has said this is a preference, not a hard requirement.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1, Q2
- authority: proposed
- hypothesis: H1

#### M2
- statement: Write the CSV as UTF-8 with a byte order mark.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: O1, AC2
- authority: proposed
- hypothesis: H2

#### M3
- statement: Use semicolons as field separators, because the München office uses German Excel.
- claim_type: hypothesis
- attributed_to: owner
- source: Q2
- authority: proposed
- hypothesis: H3

### Hypotheses

#### H1
- statement: Producing the export with pandas (M1) achieves O1.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: Generate the export with pandas, open it by double-click in the Excel version and regional settings used at the München office, and check that ä, ö, ü and ß display correctly and the columns are split correctly.

#### H2
- statement: The earlier garbled umlauts came from an encoding mismatch (UTF-8 bytes read by Excel as a legacy Windows code page), and writing UTF-8 with a byte order mark (M2) makes Excel display the characters correctly.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: M2
- authority: proposed
- test: Open the same customer data exported once as UTF-8 without a byte order mark and once with it, in the München office's Excel configuration, and compare how ä, ö, ü and ß are shown.

#### H3
- statement: German Excel at the München office splits a semicolon-separated file (M3) into the correct columns when it is opened.
- claim_type: hypothesis
- attributed_to: owner
- source: M3
- authority: proposed
- test: Open a semicolon-separated export in the München office's Excel and regional settings, in the way agreed in CL4, and check that name, email and city each appear in their own column, including values that contain commas or semicolons.

### Acceptance Criteria

#### AC1
- statement: A member of the sales team can obtain a CSV file that contains every active customer (as defined in CL6), each with name, email and city, through the delivery agreed in CL3.
- claim_type: requirement
- attributed_to: owner
- source: O1, Q2, CL3, CL6
- authority: proposed

#### AC2
- statement: When the exported file is opened in Excel at the München office (German Excel, in the version and way named in CL4), every ä, ö, ü and ß, and any other non-ASCII character in the customer data, is displayed exactly as stored in the source data.
- claim_type: requirement
- attributed_to: owner
- source: O1, CL4
- authority: proposed

#### AC3
- statement: When the exported file is opened in Excel at the München office (as specified in CL4), each field appears in its own column and each customer in its own row, without manual import steps, unless CL4 establishes that a manual import is acceptable.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1, CL4
- authority: proposed

### Open Clarifications

#### CL1
- question: Is the use of pandas a binding requirement (for example a team standard or an existing pipeline), and if so, why? Or is it a preferred way of doing it that another approach could replace if it meets the objective?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If binding, M1 is promoted to a constraint once the acceptance is recorded, and the design must work within pandas. If not, the design may choose any method that meets AC2 and AC3.
- blocks: M1, H1
- status: resolved
- resolution: conversation:qual-04/message-2

#### CL2
- question: Which customers and which fields should the export contain (all customers or a filtered subset, which columns, in which order)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines the scope of the data, the content of AC1, and whether personal data handling or access restrictions apply.
- blocks: O1, AC1
- status: resolved
- resolution: conversation:qual-04/message-2

#### CL3
- question: How should the sales team get the export: a one-off file delivered to them, a recurring scheduled export, or a function they trigger themselves in an application? Who may run it, and is access to customer data, including email addresses, restricted?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, Q2
- consequence: Changes the scope (a one-time script versus a product feature), the cost, and the access-control and data-protection risk.
- blocks: O1, AC1
- status: open

#### CL4
- question: The München office uses German Excel. Which Excel version and operating system does it use, and does "open properly" mean opening the file by double-click, or is using Excel's import dialog acceptable?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, Q2
- consequence: The encodings Excel recognises and the separator it applies on double-click depend on the version and the system's regional list separator. This changes what AC2 and AC3 check and whether M2 and M3 fit.
- blocks: AC2, AC3, M2, H2, M3, H3
- status: open

#### CL5
- question: Which export produced the garbled umlauts last time, and is this request to fix that existing export or to create a new one? Can a sample of the broken file be provided?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines whether the change modifies an existing capability or adds a new one, and a sample would allow H2's suspected cause to be confirmed or refuted.
- blocks: O1, H2
- status: open

#### CL6
- question: What makes a customer "active": an existing status field in the customer data, recent activity within some period, or something else?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q2
- consequence: Determines which customers the export contains and therefore what AC1 checks, and whether the selection can use an existing field or needs new logic.
- blocks: AC1
- status: open

## Why

The sales team needs the customer list as a CSV file that opens properly in Excel at the München office (O1). A previous export showed German characters such as ä, ö, ü and ß as garbage, which makes customer names and cities unreadable for that office. Reliable, correctly encoded exports of all active customers with name, email and city let the sales team work with the customer data directly. The meaning of "active", the delivery method and the remaining Excel details still need to be clarified (CL3, CL4, CL6).

## What Changes

- The sales team can obtain a CSV export of all active customers with name, email and city. The definition of "active" and the delivery are to be agreed in CL6 and CL3.
- In the München office's German Excel, the exported file displays umlauts, ß and other non-ASCII characters exactly as stored.
- In that Excel, the exported file opens with fields in separate columns and customers in separate rows.
- The Owner's preference for pandas (M1), the Owner's suggestion of semicolon separators (M3) and an agent-proposed UTF-8 with byte order mark encoding (M2) are hypotheses for the design to evaluate. None is a commitment; the Owner has said pandas is not a hard requirement.

## Capabilities

### New Capabilities
- `customer-list-export`: export of the active customers' name, email and city as a CSV file for the sales team that opens correctly in German Excel with German characters intact.

### Modified Capabilities

None. This may change to an existing export capability depending on the answer to CL5.

## Impact

- Customer data source: read access to customer name, email, city and whatever determines "active" (CL6).
- The export code or tooling: new, or the existing export identified in CL5.
- Possible dependency on pandas, as a preference only (M1).
- Data-protection and access considerations for personal data, including email addresses, handed to the sales team (CL3).