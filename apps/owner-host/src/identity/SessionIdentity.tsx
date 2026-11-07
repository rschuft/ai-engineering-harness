import { useOwnerIdentity } from "./IdentityContext";
import { shortSessionId } from "./session-identity";

/**
 * Displays the Owner's session identity. It says plainly that the value is a
 * local session, not a sign-in.
 */
export function SessionIdentity({ compact = false }: { compact?: boolean }) {
  const identity = useOwnerIdentity();
  const short = shortSessionId(identity);
  const scope = identity.persisted ? "Local session" : "Local session, this page only";
  return (
    <div
      className="owner-identity"
      data-testid="session-identity"
      data-session-id={identity.sessionId}
      data-compact={compact ? "true" : "false"}
      title={`${scope}: ${identity.sessionId}. Not signed in: no authentication is configured.`}
    >
      <span className="owner-identity__role">Owner</span>
      <span className="owner-identity__session">
        {compact ? null : <span className="owner-identity__label">{scope} </span>}
        <code className="owner-identity__id" data-testid="session-identity-short">
          {short}
        </code>
      </span>
      {compact ? null : <span className="owner-identity__auth">Not signed in</span>}
    </div>
  );
}
