import { useState, type FormEvent } from "react";
import { useAui } from "@assistant-ui/react";
import { fieldLine, formatRequest, type RequestFields } from "./chat-adapter";

// The request form of the Owner chat (plan leaf P-01.3; I1 work design R6):
// a requested change is entered as labelled fields, the change's name, its
// objective, its acceptance criteria and optional suggestions, and sent as
// ONE message in the fixed layout (formatRequest). The preview shows exactly
// the text that is sent, stored and quoted. Each field is one line; a
// suggestion is a method the Owner proposes and is recorded as a hypothesis,
// never as the objective.

const CHANGE_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function List({
  label,
  items,
  onChange,
  addLabel,
}: {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  addLabel: string;
}) {
  return (
    <fieldset className="owner-request__list">
      <legend>{label}</legend>
      {items.map((item, index) => (
        <input
          key={index}
          type="text"
          className="owner-request__input"
          aria-label={`${label} ${index + 1}`}
          value={item}
          onChange={(event) => onChange(items.map((value, i) => (i === index ? event.target.value : value)))}
        />
      ))}
      <button type="button" className="owner-request__add" onClick={() => onChange([...items, ""])}>
        {addLabel}
      </button>
    </fieldset>
  );
}

const EMPTY: RequestFields = { change: "", objective: "", criteria: [""], suggestions: [] };

export function RequestForm() {
  const aui = useAui();
  const [fields, setFields] = useState<RequestFields>(EMPTY);
  const change = fieldLine(fields.change);
  const ready =
    CHANGE_NAME.test(change) &&
    fieldLine(fields.objective).length > 0 &&
    fields.criteria.some((criterion) => fieldLine(criterion).length > 0);
  const text = formatRequest(fields);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    aui.thread().append({ role: "user", content: [{ type: "text", text }] });
    setFields(EMPTY);
  }

  return (
    <form className="owner-request" aria-label="Request a change" data-testid="request-form" onSubmit={submit}>
      <label className="owner-request__field">
        Change name (lower-case words joined by hyphens)
        <input
          type="text"
          className="owner-request__input"
          aria-label="Change name"
          value={fields.change}
          onChange={(event) => setFields({ ...fields, change: event.target.value })}
        />
      </label>
      <label className="owner-request__field">
        Objective
        <input
          type="text"
          className="owner-request__input"
          aria-label="Objective"
          value={fields.objective}
          onChange={(event) => setFields({ ...fields, objective: event.target.value })}
        />
      </label>
      <List
        label="Acceptance criterion"
        items={fields.criteria}
        onChange={(criteria) => setFields({ ...fields, criteria })}
        addLabel="Add a criterion"
      />
      <List
        label="Suggestion (a method you propose; recorded as a hypothesis, not as the objective)"
        items={fields.suggestions}
        onChange={(suggestions) => setFields({ ...fields, suggestions })}
        addLabel="Add a suggestion"
      />
      <pre className="owner-request__preview" data-testid="request-preview" aria-label="The message that is sent">
        {text}
      </pre>
      <button type="submit" className="owner-request__send" disabled={!ready}>
        Send the request
      </button>
    </form>
  );
}
