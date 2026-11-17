import { Link, useInRouterContext } from "react-router";
import { canvasConversationUrl, engineeringSessionPath } from "./session-detail";

// The shell's only link and frame whose address carries a projection-supplied value (plan leaf U-01.2).
// Each address comes from session-detail.ts's checked builder alone (a lower-case UUID inside a
// shell-owned template); when the builder gives none, nothing is rendered but the stated refusal.

/**
 * The link from an outcome card to the shell's own engineering route for OUTCOME and CONVERSATION. Inside the
 * shell's router it navigates there; elsewhere (a card rendered alone) it is a plain same-origin link to the
 * same path. Null when either value is not an id.
 */
export function SessionDetailLink({ outcome, conversation }: { outcome: unknown; conversation: unknown }) {
  const routed = useInRouterContext();
  const sessionPath = engineeringSessionPath(outcome, conversation);
  if (sessionPath === null) return null;
  const label = "Open the session detail (FIXTURE)";
  return routed ? (
    <Link className="owner-outcome__session-detail" data-testid="outcome-session-detail" to={sessionPath}>
      {label}
    </Link>
  ) : (
    <a className="owner-outcome__session-detail" data-testid="outcome-session-detail" href={sessionPath}>
      {label}
    </a>
  );
}

/**
 * Agent Canvas's view of CONVERSATION, framed from its own origin (never the shell's: decision 0026 point 8; R4).
 *
 * - `src`: the shell's constant Canvas origin and `/conversations/<id>`: no credential, no query, nothing else.
 * - `sandbox="allow-scripts allow-same-origin allow-forms"`, the minimum the standalone application needs: its
 *   scripts; its own origin (its storage holds the backend registry and its onboarding state, and its requests go
 *   to its own origin through upstream's proxy; without it the frame's origin would be opaque and those requests
 *   cross-origin, which the server does not allow); and forms (accepted by the engineering manager: Canvas's
 *   composer and dialogs are forms). Not granted: popups, top-level navigation, modals, downloads, pointer lock,
 *   presentation. A framed page can lift its own sandbox only when it is on its embedder's origin; this frame is
 *   cross-origin to the shell (127.0.0.1:13330, not the shell's port), so it cannot, and it can reach nothing of the
 *   shell's. The shell's own content-security policy frames this origin only (`frame-src http://127.0.0.1:13330`).
 * - `referrerPolicy="no-referrer"`: the frame's request carries no Referer (the shell's address).
 * - `allow=""`: no permission-policy feature (camera, microphone, geolocation, clipboard ...) is delegated.
 *
 * Null when CONVERSATION is not an id.
 */
export function CanvasFrame({ conversation, title }: { conversation: unknown; title: string }) {
  const frameUrl = canvasConversationUrl(conversation);
  if (frameUrl === null) return null;
  return (
    <iframe
      className="owner-canvas-frame__view"
      data-testid="canvas-frame"
      title={title}
      src={frameUrl}
      sandbox="allow-scripts allow-same-origin allow-forms"
      referrerPolicy="no-referrer"
      allow=""
    />
  );
}
