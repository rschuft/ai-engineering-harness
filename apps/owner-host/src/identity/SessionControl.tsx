import { Link } from "react-router";
import { useOwnerSession } from "./OwnerSessionContext";

/** The header's sign-in link, or its "Sign out" button once signed in. */
export function SessionControl() {
  const { state, signOut } = useOwnerSession();
  if (state.status === "signed-in" || state.status === "unreachable") {
    return (
      <button type="button" className="owner-session-control" data-testid="sign-out" onClick={signOut}>
        Sign out
      </button>
    );
  }
  return (
    <Link to="/sign-in" className="owner-session-control" data-testid="sign-in-link">
      Sign in
    </Link>
  );
}
