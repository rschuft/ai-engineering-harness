import { useOwnerIdentity } from "./IdentityContext";
import { useOwnerSession } from "./OwnerSessionContext";
import { shortSessionId } from "./session-identity";

/**
 * Displays the Owner's session identity. It says plainly that the value is a
 * local session, and whether the Owner is signed in to the Integration
 * process (U-01.3).
 */
export function SessionIdentity({ compact = false }: { compact?: boolean }) {
  const identity = useOwnerIdentity();
  const { state } = useOwnerSession();
  const short = shortSessionId(identity);
  const scope = identity.persisted ? "Local session" : "Local session, this page only";
  const signedIn = state.status === "signed-in";
  const auth = signedIn ? "Signed in" : state.status === "checking" ? "Checking sign-in" : "Not signed in";
  return (
    <div
      className="owner-identity"
      data-testid="session-identity"
      data-session-id={identity.sessionId}
      data-compact={compact ? "true" : "false"}
      data-signed-in={signedIn ? "true" : "false"}
      title={`${scope}: ${identity.sessionId}. ${auth} to the Integration process.`}
    >
      <span className="owner-identity__role">Owner</span>
      <span className="owner-identity__session">
        {compact ? null : <span className="owner-identity__label">{scope} </span>}
        <code className="owner-identity__id" data-testid="session-identity-short">
          {short}
        </code>
      </span>
      {compact ? null : <span className="owner-identity__auth">{auth}</span>}
    </div>
  );
}
