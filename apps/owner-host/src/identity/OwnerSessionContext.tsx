import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  clearStoredCredential,
  createIntegrationClient,
  defaultStorage,
  isCredentialShaped,
  loadStoredCredential,
  SessionRefusal,
  storeCredential,
  verifyCredential,
  type FetchLike,
  type IntegrationClient,
  type OwnerSession,
  type RefusalCode,
} from "./owner-session";

// The Owner's sign-in to the Integration process (plan leaf U-01.3; Proposed
// decision 0025, point 4). It sits above the router, beside the local session
// identity, so that every area reads one state and navigation never resets it.

export type OwnerSessionState =
  | { status: "signed-out"; refusal: RefusalCode | null }
  | { status: "checking" }
  | { status: "signed-in"; session: OwnerSession }
  | { status: "unreachable"; session: OwnerSession };

export interface OwnerSessionValue {
  state: OwnerSessionState;
  /** Verify the credential with the Integration process; on success keep it in localStorage. */
  signIn(credential: string): Promise<boolean>;
  /** Remove the shell's copy. */
  signOut(): void;
  /** The client for the signed-in session, or null. */
  client: IntegrationClient | null;
}

const OwnerSessionContext = createContext<OwnerSessionValue | null>(null);

type Storage_ = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function OwnerSessionProvider({
  children,
  fetchImpl,
  storage,
}: {
  children: ReactNode;
  /** Tests pass a fake; the app uses the browser's fetch. */
  fetchImpl?: FetchLike;
  /** Tests may pass storage; the app uses window.localStorage. */
  storage?: Storage_ | null;
}) {
  const store = storage === undefined ? defaultStorage() : storage;
  const [credential, setCredential] = useState<string | null>(() => loadStoredCredential(store)?.credential ?? null);
  const [state, setState] = useState<OwnerSessionState>(() => {
    const stored = loadStoredCredential(store);
    return stored ? { status: "checking" } : { status: "signed-out", refusal: null };
  });
  const checked = useRef(false);

  const refuse = useCallback(
    (refusal: SessionRefusal) => {
      if (refusal.credentialRefused || refusal.code === "NOT_SHAPED") {
        clearStoredCredential(store);
        setCredential(null);
      }
      return refusal.code;
    },
    [store],
  );

  // A stored copy is verified once when the shell opens (the browser may have been closed and reopened).
  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    const stored = loadStoredCredential(store);
    if (!stored) return;
    verifyCredential(stored.credential, fetchImpl).then(
      (session) => {
        storeCredential({ credential: stored.credential, ...session }, store);
        setState({ status: "signed-in", session });
      },
      (error: unknown) => {
        if (error instanceof SessionRefusal && error.code === "UNREACHABLE") {
          setState({ status: "unreachable", session: stored });
          return;
        }
        const code = error instanceof SessionRefusal ? refuse(error) : "ANSWER_INVALID";
        setState({ status: "signed-out", refusal: code });
      },
    );
  }, [fetchImpl, refuse, store]);

  const signIn = useCallback(
    async (candidate: string) => {
      if (!isCredentialShaped(candidate)) {
        setState({ status: "signed-out", refusal: "NOT_SHAPED" });
        return false;
      }
      setState({ status: "checking" });
      try {
        const session = await verifyCredential(candidate, fetchImpl);
        storeCredential({ credential: candidate, ...session }, store);
        setCredential(candidate);
        setState({ status: "signed-in", session });
        return true;
      } catch (error) {
        const code = error instanceof SessionRefusal ? error.code : "ANSWER_INVALID";
        setState({ status: "signed-out", refusal: code });
        return false;
      }
    },
    [fetchImpl, store],
  );

  const signOut = useCallback(() => {
    clearStoredCredential(store);
    setCredential(null);
    setState({ status: "signed-out", refusal: null });
  }, [store]);

  const client = useMemo(
    () => (credential && state.status === "signed-in" ? createIntegrationClient(credential, fetchImpl) : null),
    [credential, fetchImpl, state.status],
  );

  const value = useMemo(() => ({ state, signIn, signOut, client }), [state, signIn, signOut, client]);
  return <OwnerSessionContext.Provider value={value}>{children}</OwnerSessionContext.Provider>;
}

export function useOwnerSession(): OwnerSessionValue {
  const value = useContext(OwnerSessionContext);
  if (!value) throw new Error("useOwnerSession must be used inside <OwnerSessionProvider>");
  return value;
}
