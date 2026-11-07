import { RouterProvider, type createBrowserRouter } from "react-router";
import { IdentityProvider } from "./identity/IdentityContext";
import type { OwnerSessionIdentity } from "./identity/session-identity";

type Router = ReturnType<typeof createBrowserRouter>;

/**
 * The Owner host: one session identity above one router. The identity provider
 * sits outside the router so no navigation can remount or re-resolve it.
 */
export function OwnerApp({ router, identity }: { router: Router; identity?: OwnerSessionIdentity }) {
  return (
    <IdentityProvider identity={identity}>
      <RouterProvider router={router} />
    </IdentityProvider>
  );
}
