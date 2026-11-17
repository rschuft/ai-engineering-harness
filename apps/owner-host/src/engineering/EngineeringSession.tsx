import { useParams } from "react-router";
import { useOwnerSession } from "../identity/OwnerSessionContext";
import { FixtureLabel, StatusBadge, useOutcomeProjection } from "../areas/outcome-card";
import { str, type Json } from "../areas/outcome-projection";
import { CanvasFrame } from "./SessionLinks";
import { checkedId, sessionDetailOf } from "./session-detail";

// The engineering session route (plan leaf U-01.2; blueprint UI-01's fallback; the I1 design R14 and R15):
// /engineering/outcomes/<outcome id>/sessions/<conversation id>. The selection is the route's own
// address, so a refresh, a bookmark or a reopened browser keeps it. The route reads the outcome's
// projection (U-04.1) through the signed-in Integration client, finds the attempt whose session-detail
// action names this conversation, and shows its fixture label, its status as the projection states it,
// and Agent Canvas's view of the conversation in a frame from Canvas's own origin (SessionLinks.tsx).
// Nothing is shown in a frame unless both ids pass the check and the projection's action is available
// for this conversation; otherwise the refusal is shown. No credential goes to the frame: its address
// is the shell's constant Canvas origin and the conversation id, and the shell sends it nothing else.

function attemptFor(attempts: Json[], conversation: string): Json | null {
  const matching = attempts.filter((a) => {
    const detail = sessionDetailOf(a);
    return detail.available && detail.conversationId === conversation;
  });
  return matching.length > 0 ? matching[matching.length - 1] : null;
}

export function EngineeringSession() {
  const params = useParams();
  const outcome = checkedId(params.outcomeId);
  const conversation = checkedId(params.conversationId);
  const { state, client } = useOwnerSession();
  const { read } = useOutcomeProjection(outcome !== null && conversation !== null ? client : null, outcome);
  let body;
  if (outcome === null || conversation === null) {
    body = (
      <p role="status" data-testid="engineering-session-refused" data-reason="NOT_AN_ID">
        This address does not name an outcome and a conversation by their ids, so no session is shown.
      </p>
    );
  } else if (state.status !== "signed-in" || client === null) {
    body = (
      <p role="status" data-testid="engineering-session-signed-out">
        Sign in to read this outcome&apos;s projection; the session is shown once it confirms the session detail.
      </p>
    );
  } else if (read.state === "loading") {
    body = (
      <p role="status" data-testid="engineering-session-loading">
        Reading the outcome projection…
      </p>
    );
  } else if (read.state !== "shown") {
    body = (
      <p role="status" data-testid="engineering-session-refused" data-reason={read.state === "refused" ? read.code : read.state}>
        The outcome projection was not read ({read.state === "refused" ? read.code : read.state}), so no session is shown.
      </p>
    );
  } else {
    const attempt = attemptFor(read.projection.attempts, conversation);
    if (attempt === null) {
      const refused = read.projection.attempts
        .map((a) => sessionDetailOf(a))
        .find((d) => !d.available) as { code: string; reason: string } | undefined;
      body = (
        <p role="status" data-testid="engineering-session-refused" data-reason={refused?.code ?? "SESSION_ACCESS_UNAVAILABLE"}>
          The outcome&apos;s projection gives no session detail for this conversation, so no session is shown
          {refused ? <>: {refused.reason}</> : "."}
        </p>
      );
    } else {
      body = (
        <>
          <p className="owner-engineering__fixture" data-testid="engineering-fixture-label">
            <FixtureLabel testId="engineering-session-fixture">
              : this session is served by the deterministic Agent Server fixture, not a live run.
            </FixtureLabel>
          </p>
          <div className="owner-engineering__status" data-testid="engineering-session-status">
            The attempt (stage <code>{str(attempt.stage) ?? "?"}</code>), as the dispatcher&apos;s records show it:{" "}
            <StatusBadge status={attempt.executionStatus} code={attempt.executionCode} />
          </div>
          <div className="owner-canvas-frame" role="region" aria-label="Agent Canvas session">
            <CanvasFrame conversation={conversation} title="Agent Canvas: the engineering session (fixture)" />
          </div>
        </>
      );
    }
  }
  return (
    <section className="owner-area owner-area--engineering" aria-labelledby="engineering-session-heading" data-testid="area-engineering-session">
      <h2 id="engineering-heading" className="owner-area__title">
        Engineering
      </h2>
      <h3 id="engineering-session-heading">Engineering session</h3>
      {body}
    </section>
  );
}
