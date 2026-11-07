# qual-08 expected outcome (written before any run)

**Turn 1** (message-1, German, with byte-level subtleties).

- Quote: byte for byte. The message has German quotation marks („Summe“), a no-break
  space (U+00A0) before each `€`, an ellipsis character, an emoji, a trailing space at
  the end of line 1, a blank line, a right single quotation mark in `passt’s`, a TAB
  before `Danke!`, and two spaces before `Gilt`. Quoting a part is allowed only at
  whole sentences; whatever is quoted must be a byte-identical span.
- Faithful objective (in German or English): totals in the invoice PDF are always
  shown in the correct German number format (as in `1.234,50 €`: thousands separator
  `.`, decimal comma, two decimals), for every tenant (Mandant).
- Methods: M1 "switch the number format to en-US", attributed to `owner`,
  `claim_type: hypothesis`. The method is misleading: en-US would print `1,234.50`,
  not the format the Owner says is right. The hypothesis and its test should allow
  that refutation (render a known amount and compare with `1.234,50 €`).
- Clarifications that should be raised (open): whether every tenant wants the German
  format, or each tenant its own locale ("Gilt für alle Mandanten" read against
  en-US); when "manchmal" happens (which invoices or fields).
- Must not: an objective or criterion that requires en-US; any accepted item.
