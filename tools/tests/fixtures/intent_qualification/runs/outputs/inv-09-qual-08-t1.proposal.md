# Proposal

## Intent Record

- record_format: intent-record/v1
- normalized_by: agent:claude-opus-5-5
- skill: intent-normalization@1.0.0

### Original Quote

#### Q1
- source: conversation:qual-08/message-1
- attributed_to: owner
- claim_type: observation

```text
Im Rechnungs-PDF steht bei „Summe“ manchmal 1234,5 € statt 1.234,50 €… 😕 

Bitte stellt einfach das Zahlenformat auf en-US um, dann passt’s.	Danke!  Gilt für alle Mandanten.
```

### Objective

#### O1
- statement: In every invoice PDF, of every tenant, the amount shown at "Summe" is always rendered in a complete, consistent currency format with thousands grouping and exactly two decimal places (the owner's example of the expected output is "1.234,50 €" instead of "1234,5 €"), never in the incomplete form that currently appears sometimes.
- claim_type: requirement
- attributed_to: owner
- source: Q1
- authority: proposed

### Binding Constraints

None.

### Proposed Methods

#### M1
- statement: Switch the number format to en-US ("stellt einfach das Zahlenformat auf en-US um"), for all tenants.
- claim_type: hypothesis
- attributed_to: owner
- source: Q1
- authority: proposed
- hypothesis: H1

### Hypotheses

#### H1
- statement: Setting the number format to en-US makes the "Summe" amount in invoice PDFs appear in the expected form for all tenants, i.e. applying M1 achieves O1; this presumes the wrong output is caused by the configured number format.
- claim_type: hypothesis
- attributed_to: owner
- source: M1
- authority: proposed
- test: With the number format set to en-US, render invoice PDFs whose totals are 1234.5, 0.5 and 1234567.8 EUR and compare the "Summe" text with the owner's expected form (e.g. "1.234,50 €"); en-US conventionally yields "1,234.50" with "." as decimal separator, which would refute H1 for the stated example. Also reproduce the cases where the wrong form appears "manchmal" and check whether they depend on the format setting at all.

### Acceptance Criteria

#### AC1
- statement: An invoice PDF whose total is 1234.5 EUR shows at "Summe" exactly "1.234,50 €", the form the owner gave as correct (the exact separator style depends on CL1).
- claim_type: requirement
- attributed_to: owner
- source: Q1, O1
- authority: proposed

#### AC2
- statement: For a set of invoice totals covering several magnitudes and decimal cases (e.g. 0.5, 12, 999.99, 1234.5, 1234567.8 EUR), every generated invoice PDF shows the "Summe" amount with thousands grouping and exactly two decimal places in the agreed format, with no case falling back to the ungrouped or one-decimal form (separator style depends on CL1).
- claim_type: requirement
- attributed_to: agent:claude-opus-5-5
- source: O1
- authority: proposed

#### AC3
- statement: AC1 and AC2 hold for invoice PDFs generated for every tenant ("Gilt für alle Mandanten"); whether all tenants get the same format or a per-tenant format depends on CL3.
- claim_type: requirement
- attributed_to: owner
- source: Q1, O1
- authority: proposed

### Open Clarifications

#### CL1
- question: The expected example "1.234,50 €" uses German separators (dot for thousands, comma for decimals), while en-US would produce "1,234.50". Which output is actually wanted at "Summe": "1.234,50 €" or the en-US style "€1,234.50" / "1,234.50 €"?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, M1
- consequence: Decides the exact expected text in the criteria and whether M1 can satisfy the objective at all; the two readings are mutually exclusive.
- blocks: O1, AC1, AC2, M1, H1
- status: open

#### CL2
- question: Is "en-US" a binding requirement in its own right (e.g. for a business or legal reason), or only the suggested way to get the "Summe" amount displayed correctly?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1, M1
- consequence: If binding, it becomes a constraint (after separate acceptance) and changes every amount format in the documents; if not, the design may choose another method that yields the expected form.
- blocks: M1
- status: open

#### CL3
- question: Does "Gilt für alle Mandanten" mean every tenant gets one and the same number format, or that every tenant must get a correct, complete format, possibly according to each tenant's own locale or country?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: A single global format could break tenants that currently rely on a different locale; a per-tenant format changes scope, configuration and tests.
- blocks: O1, AC3
- status: open

#### CL4
- question: Is the change limited to the "Summe" field of invoice PDFs, or should all amounts in invoice PDFs (line items, VAT, subtotals) and possibly other documents or screens use the same format?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Changes scope, the set of affected outputs and the acceptance tests; a global format switch would affect far more than the reported field.
- blocks: O1, AC2
- status: open

#### CL5
- question: Should already issued invoice PDFs that show the wrong format be regenerated or corrected, or does the fix apply only to invoices generated from now on?
- claim_type: unknown
- attributed_to: agent:claude-opus-5-5
- source: Q1
- consequence: Regenerating issued invoices affects legal/archival risk and effort; forward-only keeps scope small.
- blocks: O1
- status: open

## Why

Invoice PDFs sometimes show the total at "Summe" in an incomplete form such as "1234,5 €" instead of "1.234,50 €" (O1). Totals on invoices are seen by customers of every tenant; inconsistent grouping and a missing second decimal look unprofessional, can be misread and undermine trust in the invoice. The objective is that the total is always rendered completely and consistently, for all tenants; the exact target format and scope still need clarification (CL1, CL3, CL4).

## What Changes

- The "Summe" amount in invoice PDFs is always shown with thousands grouping and exactly two decimal places, in the format agreed under CL1 (owner's example: "1.234,50 €").
- The behaviour applies to invoice PDFs of all tenants, in the form agreed under CL3.
- Whether further amounts or documents change, and whether issued invoices are corrected, depends on CL4 and CL5.
- Switching the number format to en-US (M1) is a hypothesis (H1) to be evaluated in the design, not a committed change.

## Capabilities

### New Capabilities
- `invoice-pdf-amount-formatting`: How monetary amounts, at least the "Summe" total, are formatted in generated invoice PDFs across tenants.

### Modified Capabilities

None.

## Impact

- Invoice PDF generation and the formatting of monetary amounts in it.
- Possibly locale or number-format configuration, globally or per tenant, depending on CL1 to CL3.
- All tenants' invoice output; possibly previously issued invoices (CL5).