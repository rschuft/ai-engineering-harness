# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

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
- statement: The sales team can obtain the customer list as a CSV file.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

#### O2
- statement: The exported file opens correctly in Excel as used by the München office, with all text including German umlauts and ß shown as written.
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
- statement: Write the CSV as UTF-8 with a byte order mark so that Excel detects the encoding.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: Q1
- authority: proposed
- hypothesis: H2

### Hypotheses

#### H1
- statement: Producing the export with pandas (M1) achieves O1 and O2.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: Generate the export with pandas from the real customer list and check AC1, AC2 and AC3 against it on a München office machine.

#### H2
- statement: The previous umlaut corruption came from Excel reading a UTF-8 file without a byte order mark as a legacy code page, so writing UTF-8 with a byte order mark (M2) makes O2 hold.
- claim_type: hypothesis
- attributed_to: agent:claude-opus-5-5
- source: M2
- authority: proposed
- test: Open a file containing ä, ö, ü, ß, Ä, Ö, Ü by double-click in the München office's Excel, once without and once with a byte order mark, and compare the displayed characters.

### Acceptance Criteria

#### AC1
- statement: A member of the sales team can obtain a CSV file containing every customer in the customer list, with the agreed fields (see CL2).
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1
- authority: proposed

#### AC2
- statement: When the exported file is opened in Excel on a München office machine, customer data containing ä, ö, ü, ß (and Ä, Ö, Ü) is displayed exactly as stored, with no garbled characters.
- claim_type: requirement
- attributed_to: owner
- source: O2, Q1
- authority: proposed

#### AC3
- statement: When the exported file is opened in Excel on a München office machine in the way staff normally open it (see CL4), each field appears in its own column without manual import steps.
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O2
- authority: proposed

### Open Clarifications

#### CL1
- question: Is the use of pandas a binding requirement (for example because of an existing toolchain or maintenance policy), and if so, will you record that acceptance separately so it can become a constraint?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: If binding, the design must use pandas; if not, the design may choose whichever method best meets O1 and O2.
- blocks: M1
- status: open

#### CL2
- question: Which customers and which fields should the export contain (all customers or a subset, and which columns)?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Determines the content of the file, the data-protection exposure of personal data given to the sales team, and what AC1 checks.
- blocks: AC1
- status: open

#### CL3
- question: Is this a one-off export, or a recurring capability the sales team can run themselves, and how should they receive the file?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Changes scope and cost from a single generated file to a feature with access control and delivery.
- blocks: O1, AC1
- status: open

#### CL4
- question: Which Excel version and regional settings does the München office use, and do staff open the file by double-click or through Excel's import dialog?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: German regional settings expect a semicolon list separator and comma decimals, so "opens properly" may require a different delimiter and number format as well as encoding; the answer decides which method fits O2.
- blocks: O2, AC2, AC3, M2
- status: open

#### CL5
- question: Can you share the previous export that showed garbled umlauts, or say how it was produced?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Confirms or refutes the suspected cause in H2 and shows whether the corruption happened in the file or already in the source data.
- blocks: H2
- status: open

## Why

The sales team needs the customer list as a CSV file (O1), and the München office must be able to open it in Excel with all text, including umlauts and ß, displayed correctly (O2). A previous export produced garbled umlauts, making the data unusable for German customer names and addresses, so correct character handling in Excel is essential for this export to be useful.

## What Changes

- The sales team can obtain a CSV export of the customer list (scope and delivery pending CL2 and CL3).
- The exported file opens in Excel on München office machines with ä, ö, ü, ß and their capitals shown correctly, and with each field in its own column (pending CL4).
- Proposed methods to be evaluated in the design, not yet committed: generating the export with pandas (M1, H1; binding status pending CL1) and writing UTF-8 with a byte order mark (M2, H2).

## Capabilities

### New Capabilities
- `customer-export`: exporting the customer list as a CSV file that opens correctly in Excel for the sales team.

### Modified Capabilities

None.

## Impact

- Reads customer data, including personal data, and makes it available to the sales team; access and field selection need review (CL2).
- Adds an export routine and possibly a user-facing trigger for it (CL3).
- May add a dependency on pandas if M1 is confirmed or accepted (CL1).