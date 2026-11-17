import { useAui, type ToolCallMessagePartComponent, type ToolCallMessagePartProps } from "@assistant-ui/react";
import { formatReview, type CaptureResult } from "./chat-adapter";

// The acknowledgement card of a captured request (plan leaf P-01.3): the
// reply to an Owner message in the request layout. It shows only what the
// Integration process answered (the change, the commit, whether this request
// made it or found it made) or its refusal, with the stable code; nothing in
// it is a model's text. A retry is the assistant-ui reload of this reply:
// the same message is captured again and the service answers the same commit.

type CaptureArgs = { messageId: string };

/** P-04.4: ask for the acceptance of the captured change's objective (O1), as the Owner's own review message. */
function ReviewButton({ change }: { change: string }) {
  const aui = useAui();
  const text = formatReview(change, "O1");
  return (
    <button
      type="button"
      className="owner-chat__capture-review"
      onClick={() => aui.thread().append({ role: "user", content: [{ type: "text", text }] })}
    >
      {text}
    </button>
  );
}

function isResult(value: unknown): value is CaptureResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  if (v.captured === true) return typeof v.change === "string" && typeof v.commit === "string";
  return v.captured === false && typeof v.code === "string" && typeof v.text === "string";
}

export const CaptureCard: ToolCallMessagePartComponent<CaptureArgs, CaptureResult> = (
  props: ToolCallMessagePartProps<CaptureArgs, CaptureResult>,
) => {
  const result = isResult(props.result) ? props.result : null;
  const state = result === null ? "unknown" : result.captured ? "captured" : "refused";
  return (
    <div
      className="owner-chat__capture"
      data-testid="capture-card"
      data-state={state}
      data-tool-call-id={props.toolCallId}
      role="group"
      aria-label="Captured request"
    >
      {result === null ? (
        <p>The capture's answer cannot be shown.</p>
      ) : result.captured ? (
        <>
          <p className="owner-chat__capture-title">
            {result.created ? "Captured" : "Already captured"} as the OpenSpec change <code>{result.change}</code>
          </p>
          <p className="owner-chat__capture-commit">
            Commit <code data-testid="capture-commit">{result.commit}</code> in the project repository.
          </p>
          {result.workTree ? (
            <p className="owner-chat__capture-work-tree" data-testid="capture-work-tree">
              The branch holds this commit, but the project&apos;s work tree or index does not hold its files
              ({result.workTree}): run git status in the project repository before you edit it.
            </p>
          ) : null}
          <p className="owner-chat__capture-note">
            Your objective and acceptance criteria are recorded in your own words; a suggestion is recorded as a
            hypothesis. Nothing was decided by a model.
          </p>
          <ReviewButton change={result.change} />
        </>
      ) : (
        <>
          <p className="owner-chat__capture-title">
            Not captured: <code data-testid="capture-code">{result.code}</code>
          </p>
          <p className="owner-chat__capture-text">{result.text}</p>
          {result.detail ? <p className="owner-chat__capture-detail">{result.detail}</p> : null}
        </>
      )}
    </div>
  );
};
