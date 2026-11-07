import { createContext, useContext, useState, type ReactNode } from "react";
import { loadOrCreateSessionIdentity, type OwnerSessionIdentity } from "./session-identity";

const IdentityContext = createContext<OwnerSessionIdentity | null>(null);

/**
 * Resolves the Owner's session identity once, when the app mounts, above the
 * router: every route reads this one value, and navigation never re-resolves it.
 */
export function IdentityProvider({
  children,
  identity,
}: {
  children: ReactNode;
  /** Tests may pass a fixed identity; the app resolves it from local storage. */
  identity?: OwnerSessionIdentity;
}) {
  const [value] = useState<OwnerSessionIdentity>(() => identity ?? loadOrCreateSessionIdentity());
  return <IdentityContext.Provider value={value}>{children}</IdentityContext.Provider>;
}

export function useOwnerIdentity(): OwnerSessionIdentity {
  const value = useContext(IdentityContext);
  if (!value) throw new Error("useOwnerIdentity must be used inside <IdentityProvider>");
  return value;
}
