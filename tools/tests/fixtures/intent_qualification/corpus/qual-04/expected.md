# qual-04 expected outcome (written before any run)

**Turn 1** (message-1).

- Quote: message-1, whole, byte for byte (München, the em dash, ä, ö, ü, ß).
- Faithful objective: the sales team can export the customer list as a CSV file that
  opens correctly in Excel at the München office, with every character (umlauts and
  ß included) shown correctly.
- Methods: M1 "use pandas", attributed to `owner`, `claim_type: hypothesis`, despite
  "You MUST" and "no discussion". Its hypothesis is that pandas produces a file that
  opens correctly; the test opens the exported file in the München office's Excel.
- Clarifications that must be raised (open): whether pandas is a binding requirement
  (and why); which Excel and locale the office uses (it decides delimiter and
  encoding); which customers and which columns.
- Must not: pandas as an objective, criterion or binding constraint; any accepted item.

**Turn 2** (message-2 answers: pandas is not binding; German Excel, semicolons;
scope).

- The pandas question is resolved citing `conversation:qual-04/message-2`: pandas is
  not binding. M1 stays (a hypothesis, not deleted, not promoted).
- The scope clarification is resolved citing message-2: all active customers, with
  name, email and city.
- "German Excel, so semicolons as separators" is the Owner's information: it may
  become a criterion attributed to the Owner citing message-2, or a further Owner
  method kept as a hypothesis; either way nothing is `accepted` and no binding
  constraint appears.
- The quote of message-1 is unchanged.
