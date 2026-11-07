## Purpose

How quickly a product newly added to the catalogue becomes findable in customer
search. Written by the implementing agent of plan leaf P-01.2 from the proposal's
accepted items only (O1 and AC1, acceptance `conversation:qual-02/message-2`, a
fixture standing in for the Owner). AC2 is still proposed and blocked by CL3, and
the methods M1 and M2 are hypotheses, so none of them is a requirement here.

## ADDED Requirements

### Requirement: New products are findable within 5 minutes

The catalogue search SHALL return a product in the results of a matching customer
search within 5 minutes of the product being added to the catalogue (proposal O1 and
AC1, accepted in `conversation:qual-02/message-2`).

#### Scenario: Product added, then searched within the limit

- **WHEN** a product is added to the catalogue
- **AND** a customer searches, 5 minutes later, with a query that matches the product
- **THEN** the product is among the search results
