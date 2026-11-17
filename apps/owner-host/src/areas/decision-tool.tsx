import type { ToolCallMessagePartComponent, ToolCallMessagePartProps } from "@assistant-ui/react";

// The tool UI for a pending Owner decision (plan leaf U-02.2; I1 work design,
// slice 6). A decision is a human tool: a tool call named owner_decision whose
// run pauses (status requires-action) until the Owner answers it here, with
// addResult. The pause comes from the run's model adapter returning status
// requires-action with the call: in the pinned assistant-ui 0.15.32,
// unstable_humanToolNames does not pause a run (gate G2's test), so a future
// producer of decisions must return requires-action itself. The pause is kept in the Owner conversation store as the
// assistant message the history adapter appended; after the browser or the
// Integration process restarts, the history adapter's load brings the same
// message back and this card shows the call still pending, once (gate G2,
// g2-runtime-gate.test.tsx). Answering it resumes the run, and the completed
// message is an update of the same message id, never a new one.
//
// No chat model is connected, so the shell itself asks nothing yet: the card
// is shown for any owner_decision call the thread holds. Any other tool call
// is shown as a tool the Owner host has no view for.

/** The human tool's name, and the runtime's human-tool option (kept; it does not pause a run by itself). */
export const DECISION_TOOL = "owner_decision";
export const HUMAN_TOOL_NAMES = [DECISION_TOOL];

export type DecisionArgs = { question: string; options: string[] };
export type DecisionResult = { choice: string };

/** The arguments as the card can show and answer them, or null when they are not a decision request. */
export function decisionArgs(args: unknown): DecisionArgs | null {
  if (typeof args !== "object" || args === null || Array.isArray(args)) return null;
  const { question, options } = args as Record<string, unknown>;
  if (typeof question !== "string" || question.length === 0) return null;
  if (!Array.isArray(options) || options.length === 0) return null;
  if (!options.every((option) => typeof option === "string" && option.length > 0)) return null;
  if (new Set(options).size !== options.length) return null;
  return { question, options: options as string[] };
}

function chosen(result: unknown): string | null {
  if (typeof result !== "object" || result === null) return null;
  const choice = (result as Record<string, unknown>).choice;
  return typeof choice === "string" ? choice : null;
}

export const DecisionToolUI: ToolCallMessagePartComponent<DecisionArgs, DecisionResult> = (
  props: ToolCallMessagePartProps<DecisionArgs, DecisionResult>,
) => {
  const request = decisionArgs(props.args);
  const answered = props.result !== undefined;
  const choice = chosen(props.result);
  return (
    <div
      className="owner-chat__decision"
      data-testid="decision-card"
      data-tool-call-id={props.toolCallId}
      data-state={answered ? "answered" : "pending"}
      role="group"
      aria-label="Decision"
    >
      {request === null ? (
        <p className="owner-chat__decision-question">This decision request cannot be shown: its question or options are missing.</p>
      ) : (
        <>
          <p className="owner-chat__decision-question">{request.question}</p>
          {answered ? (
            <p className="owner-chat__decision-answer">Answered: {choice ?? "an answer the Owner host cannot show"}</p>
          ) : (
            <div className="owner-chat__decision-options">
              <span className="owner-chat__decision-pending">Waiting for your decision</span>
              {request.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  className="owner-chat__decision-option"
                  onClick={() => props.addResult({ choice: option })}
                >
                  {option}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};

/** Any other tool call: named, never run or answered from the shell. */
export const UnknownToolUI: ToolCallMessagePartComponent = ({ toolName }) => (
  <div className="owner-chat__tool" data-testid="unknown-tool">
    The Owner host has no view for the tool {toolName}.
  </div>
);

/** The tool components of an assistant message's parts. */
export const TOOL_COMPONENTS = { by_name: { [DECISION_TOOL]: DecisionToolUI }, Fallback: UnknownToolUI };
