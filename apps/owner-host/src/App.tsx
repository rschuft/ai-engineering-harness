import { RouterProvider, type createBrowserRouter } from "react-router";
import { IdentityProvider } from "./identity/IdentityContext";
import { OwnerSessionProvider } from "./identity/OwnerSessionContext";
import type { FetchLike } from "./identity/owner-session";
import type { OwnerSessionIdentity } from "./identity/session-identity";

type Router = ReturnType<typeof createBrowserRouter>;

/**
 * The Owner host: one session identity and one sign-in state (U-01.3) above
 * one router. Both providers sit outside the router so no navigation can
 * remount or re-resolve them.
 */
export function OwnerApp({
  router,
  identity,
  fetchImpl,
}: {
  router: Router;
  identity?: OwnerSessionIdentity;
  /** Tests pass a fake for the Integration process; the app uses fetch. */
  fetchImpl?: FetchLike;
}) {
  return (
    <IdentityProvider identity={identity}>
      <OwnerSessionProvider fetchImpl={fetchImpl}>
        <RouterProvider router={router} />
      </OwnerSessionProvider>
    </IdentityProvider>
  );
}
