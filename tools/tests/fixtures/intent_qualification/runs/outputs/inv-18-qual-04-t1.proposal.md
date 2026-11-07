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

### Objective

#### O1
- statement: The sales team can obtain the customer list as a CSV file that opens properly in Excel at the München office, with German characters such as ä, ö, ü and ß shown correctly instead of garbage.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Use pandas to produce the CSV export.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

#### M2
- statement: Write the CSV as UTF-8 with a byte order mark and use the field delimiter that the München office's Excel expects for its regional settings.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: O1, AC2, AC3
- authority: proposed
- hypothesis: H2

### Hypotheses

#### H1
- statement: Producing the export with pandas (M1) achieves O1.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: Generate the export with pandas, open it by double-click in the Excel version and regional settings used at the München office, and check that ä, ö, ü and ß display correctly and the columns are split correctly.

#### H2
- statement: The earlier garbled umlauts came from an encoding mismatch (UTF-8 bytes read by Excel as a legacy Windows code page), and writing UTF-8 with a byte order mark plus a locale-appropriate delimiter (M2) makes Excel display the characters and columns correctly.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: M2
- authority: proposed
- test: Open the same customer data exported once as UTF-8 without a byte order mark and once with it, in the München office's Excel configuration, and compare how ä, ö, ü, ß and the column split are shown.

### Acceptance Criteria

#### AC1
- statement: A member of the sales team can obtain a CSV file containing the customer list, with the records and fields agreed in CL2, through the delivery agreed in CL3.
- claim_type: requirement
- attributed_to: owner
- source: O1, CL2, CL3
- authority: proposed

#### AC2
- statement: When the exported file is opened in Excel at the München office (the Excel version and settings named in CL4), every ä, ö, ü and ß, and any other non-ASCII character in the customer data, is displayed exactly as stored in the source data.
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
- status: open

#### CL2
- question: Which customers and which fields should the export contain (all customers or a filtered subset, which columns, in which order)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines the scope of the data, the content of AC1, and whether personal data handling or access restrictions apply.
- blocks: O1, AC1
- status: open

#### CL3
- question: How should the sales team get the export: a one-off file delivered to them, a recurring scheduled export, or a function they trigger themselves in an application? Who may run it, and is access to customer data restricted?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Changes the scope (a one-time script versus a product feature), the cost, and the access-control and data-protection risk.
- blocks: O1, AC1
- status: open

#### CL4
- question: Which Excel version, operating system and regional settings does the München office use, and does "open properly" mean opening the file by double-click, or is using Excel's import dialog acceptable?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: German regional settings usually expect a semicolon delimiter, and the encodings Excel recognises differ by version and by how the file is opened. This changes what AC2 and AC3 check and which method fits.
- blocks: AC2, AC3, M2, H2
- status: open

#### CL5
- question: Which export produced the garbled umlauts last time, and is this request to fix that existing export or to create a new one? Can a sample of the broken file be provided?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines whether the change modifies an existing capability or adds a new one, and a sample would allow H2's suspected cause to be confirmed or refuted.
- blocks: O1, H2
- status: open

## Why

The sales team needs the customer list as a CSV file that opens properly in Excel at the München office (O1). A previous export showed German characters such as ä, ö, ü and ß as garbage, which makes customer names and addresses unreadable for that office. Reliable, correctly encoded exports let the sales team work with the customer data directly. The data scope, the delivery method and the Excel environment still need to be clarified (CL2 to CL4).

## What Changes

- The sales team can obtain a CSV export of the customer list. Its content and delivery are to be agreed in CL2 and CL3.
- In the München office's Excel, the exported file displays umlauts, ß and other non-ASCII characters exactly as stored.
- In that Excel, the exported file opens with fields in separate columns and customers in separate rows.
- The Owner's suggestion to use pandas (M1) and an agent-proposed encoding and delimiter approach (M2) are hypotheses for the design to evaluate. Neither is a commitment yet, and whether pandas is binding is asked in CL1.

## Capabilities

### New Capabilities
- `customer-list-export`: export of the customer list as a CSV file for the sales team that opens correctly in Excel with German characters intact.

### Modified Capabilities

None. This may change to an existing export capability depending on the answer to CL5.

## Impact

- Customer data source: read access for the export.
- The export code or tooling: new, or the existing export identified in CL5.
- Possible dependency on pandas, depending on CL1.
- Data-protection and access considerations for the customer data handed to the sales team (CL3).