import { useState } from "react";
import { useAui, type ToolCallMessagePartComponent, type ToolCallMessagePartProps } from "@assistant-ui/react";
import { formatAcceptance, type AcceptanceChallenge, type AcceptanceRecord } from "./chat-adapter";

// The acceptance cards (plan leaf P-04.4; integrations/ownerhost/acceptance.py).
//
// The challenge card (ACCEPTANCE_TOOL) is the reply to the Owner's "Review
// acceptance: O<n> of <change>" message: it shows the acceptance recorder's
// summary exactly as the Integration process answered it (the objective, the
// criteria that cite it, its authority and outcome, and the expiry), and an
// Accept form. The form sends, as the Owner's own message, exactly the text
// its preview shows: "Accept O<n> of <change>" and, when he writes any, his
// own words. Nothing here decides or records: the service records the
// acceptance on that message, bound to this session, and answers on the
// recorded card (ACCEPTANCE_RECORD_TOOL). No text on either card is a
// model's.

type ChallengeArgs = { messageId: string; change: string; item: string };
type RecordArgs = { messageId: string; change: string; item: string };

function isChallenge(value: unknown): value is AcceptanceChallenge {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  if (v.prepared === true) return typeof v.summary === "string" && typeof v.nonce === "string";
  return v.prepared === false && typeof v.code === "string" && typeof v.text === "string";
}

function isRecord(value: unknown): value is AcceptanceRecord {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  if (v.recorded === true) return typeof v.outcome === "string" && typeof v.commit === "string";
  return v.recorded === false && typeof v.code === "string" && typeof v.text === "string";
}

function AcceptForm({ change, item }: { change: string; item: string }) {
  const aui = useAui();
  const [words, setWords] = useState("");
  const text = formatAcceptance(change, item, words);

  function accept() {
    aui.thread().append({ role: "user", content: [{ type: "text", text }] });
    setWords("");
  }

  return (
    <div className="owner-chat__accept-form" data-testid="accept-form">
      <label className="owner-chat__accept-field">
        Your own words (optional)
        <textarea
          className="owner-chat__accept-words"
          aria-label="Your own words"
          value={words}
          onChange={(event) => setWords(event.target.value)}
        />
      </label>
      <pre className="owner-chat__accept-preview" data-testid="accept-preview" aria-label="The message that is sent">
        {text}
      </pre>
      <button type="button" className="owner-chat__accept" onClick={accept}>
        Accept {item} of {change}
      </button>
    </div>
  );
}

export const AcceptanceCard: ToolCallMessagePartComponent<ChallengeArgs, AcceptanceChallenge> = (
  props: ToolCallMessagePartProps<ChallengeArgs, AcceptanceChallenge>,
) => {
  const result = isChallenge(props.result) ? props.result : null;
  const state = result === null ? "unknown" : result.prepared ? "shown" : "refused";
  return (
    <div
      className="owner-chat__acceptance"
      data-testid="acceptance-card"
      data-state={state}
      data-tool-call-id={props.toolCallId}
      role="group"
      aria-label="Accept an objective"
    >
      {result === null ? (
        <p>The acceptance challenge cannot be shown.</p>
      ) : result.prepared ? (
        <>
          <p className="owner-chat__acceptance-title">
            Accept {result.item} of the change <code>{result.change}</code>?
          </p>
          <pre className="owner-chat__acceptance-summary" data-testid="acceptance-summary">
            {result.summary}
          </pre>
          <p className="owner-chat__acceptance-expiry">
            This card expires at <time dateTime={result.expiresAt}>{result.expiresAt}</time>. Your acceptance is
            recorded only from your own message, in this session.
          </p>
          <AcceptForm change={result.change} item={result.item} />
        </>
      ) : (
        <>
          <p className="owner-chat__acceptance-title">
            No challenge: <code data-testid="acceptance-code">{result.code}</code>
          </p>
          <p className="owner-chat__acceptance-text">{result.text}</p>
          {result.detail ? <p className="owner-chat__acceptance-detail">{result.detail}</p> : null}
        </>
      )}
    </div>
  );
};

export const AcceptanceRecordCard: ToolCallMessagePartComponent<RecordArgs, AcceptanceRecord> = (
  props: ToolCallMessagePartProps<RecordArgs, AcceptanceRecord>,
) => {
  const result = isRecord(props.result) ? props.result : null;
  const state = result === null ? "unknown" : result.recorded ? "recorded" : "refused";
  return (
    <div
      className="owner-chat__accepted"
      data-testid="acceptance-record-card"
      data-state={state}
      data-tool-call-id={props.toolCallId}
      role="group"
      aria-label="Recorded acceptance"
    >
      {result === null ? (
        <p>The acceptance's answer cannot be shown.</p>
      ) : result.recorded ? (
        <>
          <p className="owner-chat__accepted-title">
            {result.created ? "Accepted" : "Already accepted"}: {result.item} of <code>{result.change}</code>
          </p>
          <p className="owner-chat__accepted-outcome">
            Outcome <code data-testid="acceptance-outcome">{result.outcome}</code> (
            {result.minted ? "minted by this acceptance" : "kept: a re-acceptance keeps the id"}).
          </p>
          <p className="owner-chat__accepted-commit">
            Commit <code data-testid="acceptance-commit">{result.commit}</code> in the project repository.
          </p>
          {result.workTree ? (
            <p className="owner-chat__accepted-work-tree" data-testid="acceptance-work-tree">
              The branch holds this commit, but the project&apos;s work tree or index does not hold its files
              ({result.workTree}): run git status in the project repository before you edit it.
            </p>
          ) : null}
          <p className="owner-chat__accepted-statement">
            Your statement: <code>{result.statement}</code>
          </p>
        </>
      ) : (
        <>
          <p className="owner-chat__accepted-title">
            Not recorded: <code data-testid="acceptance-record-code">{result.code}</code>
          </p>
          <p className="owner-chat__accepted-text">{result.text}</p>
          {result.detail ? <p className="owner-chat__accepted-detail">{result.detail}</p> : null}
        </>
      )}
    </div>
  );
};
