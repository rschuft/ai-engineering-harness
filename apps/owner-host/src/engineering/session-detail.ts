// The one place the shell builds an address from a value the projection supplied (plan leaf U-01.2; the
// I1 design R4, R14 and R15; the engineering manager's refinement of the inert-text precondition).
//
// A projection value may stand in a link's or a frame's address only after it passes a strict grammar, the
// lower-case UUID, and only inside a template the shell owns: its own constant Canvas origin and its
// own route paths. Never a raw projection string, never a URL or a path the projection gave (its
// `canvasPath` is checked to be exactly what the shell would build, then not used). The outcome
// card's link and the engineering route's frame take their addresses from these functions only; a
// static test of the sources holds them to it.

/** The standalone Agent Canvas server's origin (scripts/canvas-standalone.mjs, 127.0.0.1:13330); its own origin, never the shell's. */
export const CANVAS_ORIGIN = "http://127.0.0.1:13330";
const CANVAS_CONVERSATIONS = "/conversations/";
const ENGINEERING_OUTCOMES = "/engineering/outcomes/";
const SESSIONS = "/sessions/";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** VALUE when it is a lower-case UUID, else null. */
export function checkedId(value: unknown): string | null {
  return typeof value === "string" && UUID.test(value) ? value : null;
}

/** The frame's address for CONVERSATION: the shell's constant Canvas origin and path, or null when it is not an id. */
export function canvasConversationUrl(conversation: unknown): string | null {
  const id = checkedId(conversation);
  return id === null ? null : `${CANVAS_ORIGIN}${CANVAS_CONVERSATIONS}${id}`;
}

/** The shell's own engineering route for OUTCOME and CONVERSATION, or null unless both are ids. */
export function engineeringSessionPath(outcome: unknown, conversation: unknown): string | null {
  const o = checkedId(outcome);
  const c = checkedId(conversation);
  return o === null || c === null ? null : `${ENGINEERING_OUTCOMES}${o}${SESSIONS}${c}`;
}

/** The engineering route's pattern (the shell's routes.tsx). */
export const ENGINEERING_SESSION_ROUTE = "engineering/outcomes/:outcomeId/sessions/:conversationId";

export type SessionDetail =
  | { available: true; conversationId: string }
  | { available: false; code: string; reason: string };

const REFUSED = "SESSION_ACCESS_UNAVAILABLE";

/**
 * An attempt's session-detail action as the projection states it (integrations/ownerhost/projection.py
 * session_detail): available only for a fixture authority with a conversation id that passes the check
 * and a canvasPath that is exactly the shell's own template for it; refused otherwise, with the
 * projection's reason or the shell's own.
 */
export function sessionDetailOf(attempt: unknown): SessionDetail {
  const a = typeof attempt === "object" && attempt !== null ? (attempt as Record<string, unknown>) : {};
  const d = typeof a.sessionDetail === "object" && a.sessionDetail !== null ? (a.sessionDetail as Record<string, unknown>) : null;
  if (d === null) return { available: false, code: REFUSED, reason: "The projection gives no session-detail action for this attempt." };
  if (typeof d.refused === "string") {
    return { available: false, code: d.refused, reason: typeof d.reason === "string" ? d.reason : "No reason was given." };
  }
  const id = checkedId(d.conversationId);
  if (id === null || d.canvasPath !== `${CANVAS_CONVERSATIONS}${id}` || d.authority !== "fixture") {
    return {
      available: false,
      code: REFUSED,
      reason: "The projection's session-detail action does not name a conversation id the shell accepts (a lower-case UUID) for the fixture authority.",
    };
  }
  return { available: true, conversationId: id };
}
